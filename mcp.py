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
session -- the rest of open-code (built-in tools, project hooks,
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
# stdout closes -- lets `_call` distinguish "no reply yet" from "server
# is gone."
_EOF_SENTINEL = object()


@dataclass
class MCPServer:
    """In-memory state for one connected MCP server.

    Concurrency model (post-v0.14.2):
      - One reader thread per server drains stdout, parses each JSON
        line, and routes the message to the waiter that registered for
        that id (via response_events + response_slots, both guarded by
        response_lock).
      - One stderr-drain thread per server prevents the subprocess from
        blocking on a full stderr pipe buffer.
      - `next_id` allocation is guarded by next_id_lock so two threads
        can't claim the same id.
      - `_call` uses a per-request `threading.Event` so two callers can
        wait for their OWN response without dropping each other's
        messages on the floor (this was the v0.14.1 concurrency bug).
    """
    name: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    proc: subprocess.Popen | None = None
    next_id: int = 1
    tools: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None
    reader_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    reader_stop: threading.Event = field(default_factory=threading.Event)
    eof_seen: bool = False
    next_id_lock: threading.Lock = field(default_factory=threading.Lock)
    response_lock: threading.Lock = field(default_factory=threading.Lock)
    response_events: dict[int, threading.Event] = field(default_factory=dict)
    response_slots: dict[int, dict[str, Any]] = field(default_factory=dict)
    # Bounded stderr buffer (last N lines) for diagnostics.
    stderr_buf: list[str] = field(default_factory=list)


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
                    f"[mcp: {name!r} startup failed -- {srv.last_error}]\n"
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
        # Start daemon threads: one drains stdout (dispatches responses
        # by id), one drains stderr (prevents pipe-buffer deadlock).
        srv.reader_thread = threading.Thread(
            target=self._reader_loop, args=(srv,), daemon=True,
            name=f"mcp-reader-{srv.name}",
        )
        srv.reader_thread.start()
        srv.stderr_thread = threading.Thread(
            target=self._stderr_loop, args=(srv,), daemon=True,
            name=f"mcp-stderr-{srv.name}",
        )
        srv.stderr_thread.start()

    def _reader_loop(self, srv: MCPServer) -> None:
        """Drain stdout and dispatch each response to the right waiter.

        v0.14.1 used a single Queue and dropped messages with the wrong
        id -- that was a concurrency bug. Now we look up the response
        event by id and set it directly. Messages without a registered
        waiter (notifications, late replies) are dropped on the floor;
        that's deliberate.
        """
        proc = srv.proc
        if proc is None or proc.stdout is None:
            srv.eof_seen = True
            self._wake_all_waiters(srv)
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
                if not isinstance(msg, dict):
                    continue
                msg_id = msg.get("id")
                if msg_id is None:
                    continue  # notification -- ignore for now
                with srv.response_lock:
                    if msg_id in srv.response_events:
                        srv.response_slots[msg_id] = msg
                        srv.response_events[msg_id].set()
                    # else: late reply to a call that already timed out;
                    # we have no waiter to deliver it to. Drop silently.
        except (ValueError, OSError):
            pass
        srv.eof_seen = True
        self._wake_all_waiters(srv)

    def _stderr_loop(self, srv: MCPServer) -> None:
        """Drain stderr to a bounded buffer so a chatty server can't
        block its own stderr write and starve the stdout reader."""
        proc = srv.proc
        if proc is None or proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                if srv.reader_stop.is_set():
                    break
                srv.stderr_buf.append(line)
                if len(srv.stderr_buf) > 1000:
                    # Cap at ~1000 lines of stderr to prevent unbounded growth
                    del srv.stderr_buf[0]
        except (ValueError, OSError):
            pass

    def _wake_all_waiters(self, srv: MCPServer) -> None:
        """On EOF / shutdown, signal every pending waiter so they don't
        block on a dead server until their individual timeouts."""
        with srv.response_lock:
            for ev in srv.response_events.values():
                ev.set()

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
        """Send a JSON-RPC request; wait for THIS request's response.

        Thread-safe (v0.14.2):
          - next_id allocation guarded by next_id_lock
          - Each call registers its own threading.Event in
            srv.response_events before sending. The reader thread
            dispatches each parsed message to the matching event's
            slot.
          - Two concurrent callers don't race on a single Queue; each
            blocks on its OWN Event.

        `timeout=None` reads CALL_TIMEOUT_SECS at call time so tests
        that mutate the module global between def and call get the
        updated value.
        """
        if srv.proc is None or srv.proc.stdin is None:
            raise RuntimeError("server process not initialized")
        eff_timeout = CALL_TIMEOUT_SECS if timeout is None else timeout

        # Allocate a unique id and register a waiter slot BEFORE writing
        # the request -- otherwise a very fast reply could arrive before
        # we've registered.
        with srv.next_id_lock:
            msg_id = srv.next_id
            srv.next_id += 1
        ev = threading.Event()
        with srv.response_lock:
            srv.response_events[msg_id] = ev
            if srv.eof_seen:
                # Server already gone; signal immediately and bail.
                ev.set()

        try:
            req = {"jsonrpc": "2.0", "method": method,
                   "params": params, "id": msg_id}
            try:
                srv.proc.stdin.write(json.dumps(req) + "\n")
                srv.proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise RuntimeError(
                    f"server {srv.name!r} stdin closed: {exc}"
                ) from exc

            if not ev.wait(timeout=eff_timeout):
                raise TimeoutError(
                    f"MCP call {method!r} on server {srv.name!r} "
                    f"timed out after {eff_timeout}s"
                )

            with srv.response_lock:
                msg = srv.response_slots.pop(msg_id, None)
            if msg is not None:
                return msg
            # Event was set but no slot -- server hit EOF.
            stderr_tail = "".join(srv.stderr_buf[-20:])[:500]
            raise RuntimeError(
                f"server {srv.name!r} closed stdout before reply; "
                f"stderr tail: {stderr_tail!r}"
            )
        finally:
            with srv.response_lock:
                srv.response_events.pop(msg_id, None)
                srv.response_slots.pop(msg_id, None)

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
                    "type": "object", "properties": {}
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
        srv.eof_seen = True
        self._wake_all_waiters(srv)
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
    """Ensure a tool input schema is standard JSON Schema (lowercase types).

    Pre-v0.30 this function uppercased types for Gemini. Now that
    open-code is provider-agnostic and Gemini's SDK accepts standard
    JSON Schema, we keep types lowercase so Anthropic + OpenAI can
    consume the same declarations unchanged. The Gemini adapter does
    not require uppercase; either form works.
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k == "type" and isinstance(v, str):
            out[k] = v.lower()
        elif k == "properties" and isinstance(v, dict):
            out[k] = {pk: _normalize_schema(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            out[k] = _normalize_schema(v)
        else:
            out[k] = v
    # Anthropic + OpenAI require top-level type=object on tool input_schema
    if "type" not in out:
        out["type"] = "object"
    if out.get("type") == "object" and "properties" not in out:
        out["properties"] = {}
    return out
