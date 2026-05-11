"""MCP (Model Context Protocol) client for open-code.

Spawns external "MCP servers" as subprocesses (stdio transport, JSON-RPC
over newline-delimited JSON), discovers their tools, and surfaces them
to the agent loop as namespaced tool declarations
(`mcp__<server>__<tool>`).

v0.14 scope: stdio transport only; one initialize handshake + tools/list
+ tools/call. No streaming server-sent notifications (the spec allows
them; we drain stdout but don't act on them yet).

Configuration is read from settings.json under `mcpServers`:

  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "env": { "FOO": "bar" }
    },
    "github": {
      "command": "github-mcp-server",
      "env": { "GITHUB_TOKEN": "..." }
    }
  }

Server-startup errors are logged to stderr but never kill the
session — the rest of open-code (built-in tools, project hooks,
skills) keeps working.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any


# Protocol version we advertise during initialize.
PROTOCOL_VERSION = "2024-11-05"
# Per-call timeout for blocking JSON-RPC reads (now actually enforced).
CALL_TIMEOUT_SECS = 60
# Sentinel value pushed onto the per-server queue when the server's
# stdout closes — lets `_call` distinguish "no reply yet" from "server
# is gone."
_EOF_SENTINEL = object()


@dataclass
class MCPServer:
    """In-memory state for one connected MCP server."""
    name: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    proc: subprocess.Popen | None = None
    next_id: int = 1
    tools: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None
    # The reader thread pushes parsed JSON messages here so `_call`
    # can do a Queue.get with a real timeout. Without this, `readline`
    # would block forever on a server that ACKs but never replies.
    out_queue: "queue.Queue[Any]" = field(default_factory=queue.Queue)
    reader_thread: threading.Thread | None = None
    reader_stop: threading.Event = field(default_factory=threading.Event)


class MCPClient:
    """Manages a fleet of MCP server subprocesses."""

    def __init__(self) -> None:
        self.servers: dict[str, MCPServer] = {}

    # ---- lifecycle ----

    def start_servers(self, config: dict[str, Any]) -> None:
        """Spawn + handshake every server in `config`. Tolerant of failure."""
        if not config:
            return
        for name, spec in config.items():
            if not isinstance(spec, dict):
                continue
            cmd = spec.get("command")
            if not isinstance(cmd, str):
                continue
            args = spec.get("args") or []
            if not isinstance(args, list):
                args = []
            env = spec.get("env") or {}
            if not isinstance(env, dict):
                env = {}
            srv = MCPServer(
                name=name,
                command=[cmd] + [str(a) for a in args],
                env={str(k): str(v) for k, v in env.items()},
            )
            try:
                self._spawn(srv)
                self._initialize(srv)
                self._list_tools(srv)
                self.servers[name] = srv
                sys.stderr.write(
                    f"[mcp: connected to {name!r} with "
                    f"{len(srv.tools)} tool(s)]\n"
                )
            except Exception as exc:
                srv.last_error = f"{type(exc).__name__}: {exc}"
                sys.stderr.write(
                    f"[mcp: {name!r} startup failed — {srv.last_error}]\n"
                )
                self._terminate(srv)

    def _spawn(self, srv: MCPServer) -> None:
        merged_env = os.environ.copy()
        merged_env.update(srv.env)
        srv.proc = subprocess.Popen(
            srv.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=merged_env,
            bufsize=1,
        )
        # Start a daemon reader thread that drains stdout into the queue.
        # This lets `_call` wait with a real timeout instead of blocking
        # forever on a hung server.
        srv.reader_thread = threading.Thread(
            target=self._reader_loop, args=(srv,), daemon=True,
            name=f"mcp-reader-{srv.name}",
        )
        srv.reader_thread.start()

    def _reader_loop(self, srv: MCPServer) -> None:
        """Drain server stdout into srv.out_queue. Runs in a daemon thread."""
        proc = srv.proc
        if proc is None or proc.stdout is None:
            srv.out_queue.put(_EOF_SENTINEL)
            return
        try:
            for line in proc.stdout:
                if srv.reader_stop.is_set():
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                srv.out_queue.put(msg)
        except (ValueError, OSError):
            pass
        srv.out_queue.put(_EOF_SENTINEL)

    def _initialize(self, srv: MCPServer) -> None:
        resp = self._call(srv, "initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "open-code", "version": "0.14.0"},
        })
        if "error" in resp:
            raise RuntimeError(f"initialize error: {resp['error']}")
        # Send the initialized notification (no response expected)
        self._send_notification(srv, "notifications/initialized", {})

    def _list_tools(self, srv: MCPServer) -> None:
        resp = self._call(srv, "tools/list", {})
        if "error" in resp:
            raise RuntimeError(f"tools/list error: {resp['error']}")
        tools = resp.get("result", {}).get("tools", [])
        if isinstance(tools, list):
            srv.tools = [t for t in tools if isinstance(t, dict)]

    # ---- IO ----

    def _call(self, srv: MCPServer, method: str,
              params: dict[str, Any],
              timeout: float | None = None) -> dict[str, Any]:
        """Send a JSON-RPC request; wait for the matching response with a
        real wall-clock deadline. Reader thread drains stdout into the
        queue so a hung server can't block this call indefinitely.

        `timeout=None` (default) reads CALL_TIMEOUT_SECS at call time so
        tests / users that mutate the module global between definition
        and call get the updated value.
        """
        if srv.proc is None or srv.proc.stdin is None:
            raise RuntimeError("server process not initialized")
        eff_timeout = CALL_TIMEOUT_SECS if timeout is None else timeout
        msg_id = srv.next_id
        srv.next_id += 1
        req = {"jsonrpc": "2.0", "method": method,
               "params": params, "id": msg_id}
        srv.proc.stdin.write(json.dumps(req) + "\n")
        srv.proc.stdin.flush()
        deadline = time.monotonic() + eff_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"MCP call {method!r} on server {srv.name!r} "
                    f"timed out after {eff_timeout}s"
                )
            try:
                msg = srv.out_queue.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue  # loop, check deadline
            if msg is _EOF_SENTINEL:
                stderr = ""
                try:
                    stderr = srv.proc.stderr.read() if srv.proc.stderr else ""
                except Exception:
                    pass
                raise RuntimeError(
                    f"server {srv.name!r} closed stdout; stderr: {stderr[:300]!r}"
                )
            if isinstance(msg, dict) and msg.get("id") == msg_id:
                return msg
            # else: notification or out-of-order — drop for now

    def _send_notification(self, srv: MCPServer, method: str,
                           params: dict[str, Any]) -> None:
        if srv.proc is None or srv.proc.stdin is None:
            return
        notif = {"jsonrpc": "2.0", "method": method, "params": params}
        srv.proc.stdin.write(json.dumps(notif) + "\n")
        srv.proc.stdin.flush()

    # ---- public surface ----

    def call_tool(self, namespaced_name: str,
                  args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a `mcp__<server>__<tool>` call to the right server."""
        prefix = "mcp__"
        if not namespaced_name.startswith(prefix):
            return {"ok": False,
                    "error": f"not an MCP tool name: {namespaced_name!r}"}
        rest = namespaced_name[len(prefix):]
        if "__" not in rest:
            return {"ok": False,
                    "error": f"bad MCP name (expected server__tool): "
                             f"{namespaced_name!r}"}
        server_name, _, tool_name = rest.partition("__")
        srv = self.servers.get(server_name)
        if srv is None:
            return {"ok": False,
                    "error": f"unknown MCP server: {server_name!r}"}
        try:
            resp = self._call(srv, "tools/call",
                              {"name": tool_name, "arguments": args})
        except Exception as exc:
            return {"ok": False,
                    "error": f"{type(exc).__name__}: {exc}"}
        if "error" in resp:
            return {"ok": False, "error": str(resp["error"])}
        result = resp.get("result", {})
        # MCP's `tools/call` returns {"content": [...], "isError": bool}.
        # Surface as our standard tool-result shape.
        is_error = bool(result.get("isError", False))
        return {
            "ok": not is_error,
            "content": result.get("content", []),
            "result": result,
        }

    def all_tool_declarations(self) -> list[dict[str, Any]]:
        """Render every connected MCP tool as a TOOL_DECLARATIONS entry.

        The namespace prefix prevents collisions with built-in tools and
        with other servers (e.g. two servers both exposing "read_file").
        """
        out: list[dict[str, Any]] = []
        for srv in self.servers.values():
            for tool in srv.tools:
                name = tool.get("name")
                if not isinstance(name, str):
                    continue
                description = tool.get("description") or ""
                input_schema = tool.get("inputSchema") or {
                    "type": "OBJECT", "properties": {}
                }
                # Translate JSON Schema type names to Gemini's case.
                params = _normalize_schema(input_schema)
                out.append({
                    "name": f"mcp__{srv.name}__{name}",
                    "description": f"{description} (MCP server: {srv.name})",
                    "parameters": params,
                })
        return out

    def shutdown(self) -> None:
        for srv in self.servers.values():
            self._terminate(srv)
        self.servers.clear()

    def _terminate(self, srv: MCPServer) -> None:
        srv.reader_stop.set()
        if srv.proc is None:
            return
        try:
            srv.proc.terminate()
            srv.proc.wait(timeout=2)
        except Exception:
            try:
                srv.proc.kill()
            except Exception:
                pass


def _normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Translate JSON Schema type names to Gemini's TOOL parameters shape.

    Gemini accepts JSON-Schema-like dicts but expects type names in UPPER
    CASE (OBJECT/STRING/INTEGER/BOOLEAN/NUMBER/ARRAY). We rewrite
    recursively so nested properties also work.
    """
    if not isinstance(schema, dict):
        return {"type": "OBJECT", "properties": {}}
    out: dict[str, Any] = {}
    type_map = {
        "object": "OBJECT", "string": "STRING", "integer": "INTEGER",
        "number": "NUMBER", "boolean": "BOOLEAN", "array": "ARRAY",
    }
    for k, v in schema.items():
        if k == "type" and isinstance(v, str):
            out[k] = type_map.get(v.lower(), v.upper())
        elif k == "properties" and isinstance(v, dict):
            out[k] = {pk: _normalize_schema(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            out[k] = _normalize_schema(v)
        else:
            out[k] = v
    # Ensure top-level has at least an OBJECT type
    if "type" not in out:
        out["type"] = "OBJECT"
    if out.get("type") == "OBJECT" and "properties" not in out:
        out["properties"] = {}
    return out
