"""LSP (Language Server Protocol) client for open-code.

Spawns one or more language servers as subprocesses (stdio
transport, Content-Length-framed JSON-RPC 2.0), routes
file-path-based tool calls to the right server, and exposes four
high-leverage queries to the agent loop:

  lsp_diagnostics(path)            -> list of errors/warnings
  lsp_hover(path, line, col)       -> type/doc info at a position
  lsp_definition(path, line, col)  -> jump-to-def locations
  lsp_references(path, line, col)  -> all references to a symbol

Configuration is read from settings.json under `lsp`:

  "lsp": {
    "enabled": true,
    "servers": {
      "python": {
        "command": "pyright-langserver",
        "args": ["--stdio"],
        "file_patterns": ["*.py"]
      },
      "rust": {
        "command": "rust-analyzer",
        "file_patterns": ["*.rs"]
      }
    }
  }

Lazy lifecycle: servers don't start until a tool call wants them.
Once started, they stay alive for the session.

Concurrency model mirrors mcp.py: one reader thread per server
drains stdout and dispatches by JSON-RPC id (for responses) or
URI (for publishDiagnostics notifications). A separate stderr
drainer prevents pipe-buffer deadlock on chatty servers.

Wire framing differs from MCP: LSP uses HTTP-style headers
(`Content-Length: N\\r\\n\\r\\n<JSON of length N>`), so the
subprocess pipes are opened in bytes mode rather than text mode.

LSP coordinates are 0-indexed (line 0 is the first line, col 0 is
the first column). open-code surfaces them to the agent as 0-indexed
too -- the model can grep for them in stack traces and diagnostics
without translation.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


# Per-call timeout for blocking responses (overrideable by config).
CALL_TIMEOUT_SECS = 30
# How long to wait for diagnostics after didOpen/didChange. Pyright's
# TypeScript-based server cold-starts slow (full-project scan + JIT
# compile) -- the first diagnostics on a fresh tempdir can take
# 10-15s. Subsequent files in the same server session are fast.
DIAGNOSTICS_WAIT_SECS = 20
# Severity 1=error, 2=warning, 3=info, 4=hint. Map for user display.
SEVERITY_NAMES = {1: "error", 2: "warning", 3: "info", 4: "hint"}


@dataclass
class LSPServer:
    """In-memory state for one language server."""
    name: str                                       # "python" / "rust" / ...
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    file_patterns: list[str] = field(default_factory=list)
    root_uri: str = ""
    proc: subprocess.Popen | None = None
    initialized: bool = False
    next_id: int = 1
    last_error: str | None = None
    reader_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    reader_stop: threading.Event = field(default_factory=threading.Event)
    eof_seen: bool = False
    next_id_lock: threading.Lock = field(default_factory=threading.Lock)
    response_lock: threading.Lock = field(default_factory=threading.Lock)
    response_events: dict[int, threading.Event] = field(default_factory=dict)
    response_slots: dict[int, dict[str, Any]] = field(default_factory=dict)
    # Diagnostics arrive as unsolicited textDocument/publishDiagnostics
    # notifications keyed by URI. We cache the latest per-URI list and
    # wake any waiter blocking on first-diagnostic for that URI.
    diagnostics: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    diagnostics_lock: threading.Lock = field(default_factory=threading.Lock)
    diagnostics_events: dict[str, threading.Event] = field(default_factory=dict)
    open_docs: dict[str, int] = field(default_factory=dict)  # URI -> version
    stderr_buf: list[str] = field(default_factory=list)


def path_to_uri(path: str | Path) -> str:
    """Resolve a filesystem path to a `file://` URI. Cross-platform."""
    return Path(path).resolve().as_uri()


def uri_to_path(uri: str) -> str:
    """Inverse of path_to_uri. Returns OS-native path string."""
    if not uri.startswith("file://"):
        return uri
    # urllib.parse.unquote handles %3A -> :, %20 -> space, etc.
    # Pyright RFC-encodes the colon in the drive letter; we decode
    # so the path can resolve.
    from urllib.parse import unquote
    p = unquote(uri[len("file://"):])
    # Windows: file:///C:/... -> strip leading / before drive letter
    if re.match(r"^/[A-Za-z]:", p):
        p = p[1:]
    return str(Path(p))


def _canonicalize_uri(uri: str) -> str:
    """Round-trip a URI through Path.resolve() so different encodings
    (percent-escaping, drive-letter case) of the same path produce
    the same string.

    Pyright sends `file:///c%3A/Users/...` (lowercase + escaped colon);
    our path_to_uri sends `file:///C:/Users/...`. Both refer to the
    same file. We canonicalize on store and on lookup so the dict
    keys line up.
    """
    if not uri.startswith("file://"):
        return uri
    try:
        return Path(uri_to_path(uri)).resolve().as_uri()
    except (OSError, ValueError):
        return uri


class LSPClient:
    """Manages a fleet of language-server subprocesses."""

    def __init__(self, cwd: Path | None = None) -> None:
        self.cwd = Path(cwd).resolve() if cwd else Path.cwd().resolve()
        self.servers: dict[str, LSPServer] = {}
        self.config: dict[str, Any] = {}

    # ---- lifecycle ----

    def configure(self, config: dict[str, Any]) -> None:
        """Stash config; don't spawn yet (lazy startup on first call)."""
        if not isinstance(config, dict):
            self.config = {}
            return
        if not config.get("enabled"):
            self.config = {}
            return
        servers_cfg = config.get("servers") or {}
        if not isinstance(servers_cfg, dict):
            self.config = {}
            return
        self.config = {"servers": servers_cfg}

    def _server_for_path(self, path: str) -> LSPServer | None:
        """Pick the configured server whose file_patterns match. Lazy-spawn."""
        servers_cfg = self.config.get("servers") or {}
        for name, spec in servers_cfg.items():
            if not isinstance(spec, dict):
                continue
            patterns = spec.get("file_patterns") or []
            if not isinstance(patterns, list) or not patterns:
                continue
            base = os.path.basename(path)
            if not any(fnmatch(base, str(p)) for p in patterns):
                continue
            # Match -- return existing or spawn fresh.
            srv = self.servers.get(name)
            if srv is None or srv.eof_seen:
                srv = self._spawn_and_init(name, spec)
                if srv is not None:
                    self.servers[name] = srv
            return srv
        return None

    def _spawn_and_init(
        self, name: str, spec: dict[str, Any],
    ) -> LSPServer | None:
        cmd = spec.get("command")
        if not isinstance(cmd, str):
            return None
        args = spec.get("args") or []
        if not isinstance(args, list):
            args = []
        env = spec.get("env") or {}
        if not isinstance(env, dict):
            env = {}
        patterns = [str(p) for p in (spec.get("file_patterns") or [])]
        srv = LSPServer(
            name=name,
            command=[cmd] + [str(a) for a in args],
            env={str(k): str(v) for k, v in env.items()},
            file_patterns=patterns,
            root_uri=self.cwd.as_uri(),
        )
        try:
            self._spawn(srv)
            self._initialize(srv)
            sys.stderr.write(
                f"[lsp: started {name!r} server (root={self.cwd})]\n"
            )
            return srv
        except Exception as exc:
            srv.last_error = f"{type(exc).__name__}: {exc}"
            sys.stderr.write(
                f"[lsp: {name!r} startup failed -- {srv.last_error}]\n"
            )
            self._terminate(srv)
            return None

    def _spawn(self, srv: LSPServer) -> None:
        merged_env = os.environ.copy()
        merged_env.update(srv.env)
        srv.proc = subprocess.Popen(
            srv.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,   # binary mode -- LSP framing needs raw bytes
            env=merged_env,
        )
        srv.reader_thread = threading.Thread(
            target=self._reader_loop, args=(srv,), daemon=True,
            name=f"lsp-reader-{srv.name}",
        )
        srv.reader_thread.start()
        srv.stderr_thread = threading.Thread(
            target=self._stderr_loop, args=(srv,), daemon=True,
            name=f"lsp-stderr-{srv.name}",
        )
        srv.stderr_thread.start()

    def _initialize(self, srv: LSPServer) -> None:
        resp = self._call(srv, "initialize", {
            "processId": os.getpid(),
            "rootUri": srv.root_uri,
            "workspaceFolders": [
                {"uri": srv.root_uri, "name": os.path.basename(self.cwd)},
            ],
            "capabilities": {
                "textDocument": {
                    "synchronization": {"didSave": False},
                    "publishDiagnostics": {"relatedInformation": True},
                    "hover": {"contentFormat": ["markdown", "plaintext"]},
                    "definition": {"linkSupport": False},
                    "references": {},
                },
            },
            "clientInfo": {"name": "open-code", "version": "0.32.0"},
        })
        if "error" in resp:
            raise RuntimeError(f"initialize error: {resp['error']}")
        self._send_notification(srv, "initialized", {})
        srv.initialized = True

    def _terminate(self, srv: LSPServer) -> None:
        srv.reader_stop.set()
        srv.eof_seen = True
        self._wake_all_waiters(srv)
        if srv.proc is None:
            return
        try:
            # Polite shutdown first
            self._send_notification(srv, "exit", {})
            srv.proc.terminate()
            srv.proc.wait(timeout=2)
        except Exception:
            try:
                srv.proc.kill()
            except Exception:
                pass

    def shutdown(self) -> None:
        for srv in list(self.servers.values()):
            self._terminate(srv)
        self.servers.clear()

    # ---- IO ----

    def _reader_loop(self, srv: LSPServer) -> None:
        """Read framed JSON-RPC messages and dispatch by id or URI."""
        proc = srv.proc
        if proc is None or proc.stdout is None:
            srv.eof_seen = True
            self._wake_all_waiters(srv)
            return
        try:
            while not srv.reader_stop.is_set():
                msg = self._read_message(srv)
                if msg is None:
                    break
                self._dispatch_message(srv, msg)
        except (ValueError, OSError):
            pass
        srv.eof_seen = True
        self._wake_all_waiters(srv)

    def _read_message(self, srv: LSPServer) -> dict[str, Any] | None:
        """Read one Content-Length-framed JSON-RPC message. None on EOF."""
        proc = srv.proc
        if proc is None or proc.stdout is None:
            return None
        # Read headers
        headers: dict[str, str] = {}
        while True:
            line_bytes = proc.stdout.readline()
            if not line_bytes:
                return None
            line = line_bytes.decode("ascii", errors="replace").rstrip("\r\n")
            if not line:
                break
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        try:
            n = int(headers.get("content-length", "0"))
        except ValueError:
            return None
        if n <= 0:
            return None
        # Read exactly N bytes
        body = b""
        remaining = n
        while remaining > 0:
            chunk = proc.stdout.read(remaining)
            if not chunk:
                return None
            body += chunk
            remaining -= len(chunk)
        try:
            return json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None

    def _dispatch_message(self, srv: LSPServer, msg: dict[str, Any]) -> None:
        msg_id = msg.get("id")
        method = msg.get("method")
        if msg_id is not None and method is None:
            # Response to one of our requests
            with srv.response_lock:
                if msg_id in srv.response_events:
                    srv.response_slots[msg_id] = msg
                    srv.response_events[msg_id].set()
            return
        if method == "textDocument/publishDiagnostics":
            params = msg.get("params") or {}
            uri = _canonicalize_uri(params.get("uri") or "")
            diags = params.get("diagnostics") or []
            if uri:
                with srv.diagnostics_lock:
                    srv.diagnostics[uri] = list(diags) if isinstance(diags, list) else []
                    ev = srv.diagnostics_events.get(uri)
                if ev is not None:
                    ev.set()
            return
        if method in ("window/logMessage", "window/showMessage",
                      "$/progress", "window/workDoneProgress/create",
                      "telemetry/event"):
            # Server-side logs / progress -- ignore.
            return
        # Server-to-client request we don't handle (rare). Some servers
        # need a response to keep going (e.g. workspace/configuration);
        # reply with an empty result so they don't block.
        if msg_id is not None and method is not None:
            self._send_raw(srv, {
                "jsonrpc": "2.0", "id": msg_id, "result": None,
            })

    def _stderr_loop(self, srv: LSPServer) -> None:
        proc = srv.proc
        if proc is None or proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                if srv.reader_stop.is_set():
                    break
                try:
                    text = line.decode("utf-8", errors="replace")
                except AttributeError:
                    text = str(line)
                srv.stderr_buf.append(text)
                if len(srv.stderr_buf) > 1000:
                    del srv.stderr_buf[0]
        except (ValueError, OSError):
            pass

    def _wake_all_waiters(self, srv: LSPServer) -> None:
        with srv.response_lock:
            for ev in srv.response_events.values():
                ev.set()
        with srv.diagnostics_lock:
            for ev in srv.diagnostics_events.values():
                ev.set()

    def _send_raw(self, srv: LSPServer, msg: dict[str, Any]) -> None:
        if srv.proc is None or srv.proc.stdin is None:
            return
        body = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        try:
            srv.proc.stdin.write(header + body)
            srv.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def _call(
        self, srv: LSPServer, method: str, params: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if srv.proc is None or srv.proc.stdin is None:
            raise RuntimeError("server process not initialized")
        eff_timeout = CALL_TIMEOUT_SECS if timeout is None else timeout
        with srv.next_id_lock:
            msg_id = srv.next_id
            srv.next_id += 1
        ev = threading.Event()
        with srv.response_lock:
            srv.response_events[msg_id] = ev
            if srv.eof_seen:
                ev.set()
        try:
            self._send_raw(srv, {
                "jsonrpc": "2.0", "id": msg_id,
                "method": method, "params": params,
            })
            if not ev.wait(timeout=eff_timeout):
                raise TimeoutError(
                    f"LSP call {method!r} on {srv.name!r} timed out "
                    f"after {eff_timeout}s"
                )
            with srv.response_lock:
                resp = srv.response_slots.pop(msg_id, None)
            if resp is None:
                tail = "".join(srv.stderr_buf[-10:])[:500]
                raise RuntimeError(
                    f"server {srv.name!r} closed before reply to "
                    f"{method!r}; stderr tail: {tail!r}"
                )
            return resp
        finally:
            with srv.response_lock:
                srv.response_events.pop(msg_id, None)
                srv.response_slots.pop(msg_id, None)

    def _send_notification(
        self, srv: LSPServer, method: str, params: dict[str, Any],
    ) -> None:
        self._send_raw(srv, {
            "jsonrpc": "2.0", "method": method, "params": params,
        })

    # ---- document lifecycle ----

    def _open_or_update(
        self, srv: LSPServer, path: str,
    ) -> tuple[str, str] | None:
        """Send didOpen (first call) or didChange (subsequent). Returns
        (uri, language_id) on success, None on read failure."""
        try:
            abs_path = str(Path(path).resolve())
            text = Path(abs_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        uri = path_to_uri(abs_path)
        lang_id = self._language_id_for(abs_path, srv)
        if uri in srv.open_docs:
            srv.open_docs[uri] += 1
            self._send_notification(srv, "textDocument/didChange", {
                "textDocument": {"uri": uri, "version": srv.open_docs[uri]},
                "contentChanges": [{"text": text}],
            })
        else:
            srv.open_docs[uri] = 1
            self._send_notification(srv, "textDocument/didOpen", {
                "textDocument": {
                    "uri": uri, "languageId": lang_id,
                    "version": 1, "text": text,
                },
            })
        return uri, lang_id

    @staticmethod
    def _language_id_for(path: str, srv: LSPServer) -> str:
        """Best-effort language id derived from extension + server name."""
        ext = os.path.splitext(path)[1].lower()
        return {
            ".py": "python", ".pyi": "python",
            ".rs": "rust",
            ".go": "go",
            ".ts": "typescript", ".tsx": "typescriptreact",
            ".js": "javascript", ".jsx": "javascriptreact",
            ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
        }.get(ext, srv.name)

    # ---- public tool surface ----

    def lsp_diagnostics(self, path: str) -> dict[str, Any]:
        """Return all current diagnostics for `path`.

        Strategy: pyright (and most servers) publish diagnostics in
        TWO phases after didOpen -- first an empty list ("I'm
        processing"), then the real list 1-3s later. So we can't just
        wait for "first publish"; we have to poll until quiescence.
        Algorithm:
          1. Clear any stale entry for this URI
          2. didOpen/didChange (causes server to start re-analysing)
          3. Wait up to DIAGNOSTICS_WAIT_SECS for a SECOND publish
             after the first one arrived (with a min hold of 0.5s
             between checks). Return when (a) we got at least one
             non-empty publish followed by no change for 1s, OR (b)
             the total wait budget expires.
        """
        srv = self._server_for_path(path)
        if srv is None:
            return {"ok": False,
                    "error": "no LSP server configured for this file"}
        # Resolve URI BEFORE opening so we can clear stale entries.
        abs_path = str(Path(path).resolve())
        uri = path_to_uri(abs_path)
        with srv.diagnostics_lock:
            srv.diagnostics.pop(uri, None)
            srv.diagnostics_events.pop(uri, None)

        opened = self._open_or_update(srv, path)
        if opened is None:
            return {"ok": False, "error": f"cannot read {path!r}"}

        # Poll-until-quiescent: take a snapshot every 0.25s; once we've
        # seen the same non-empty list (or stable empty) for at least
        # 1.0s, we're done.
        deadline = time.monotonic() + DIAGNOSTICS_WAIT_SECS
        stable_since: float | None = None
        last_snapshot: tuple = ()
        last_non_empty: list[dict[str, Any]] | None = None
        while time.monotonic() < deadline:
            time.sleep(0.25)
            with srv.diagnostics_lock:
                current = list(srv.diagnostics.get(uri, []))
            # Fingerprint based on length + first message (good enough
            # to detect "did it change since last poll").
            snapshot = (len(current),
                        tuple(d.get("message", "") for d in current[:3]))
            if current:
                last_non_empty = current
            if snapshot == last_snapshot:
                if stable_since is None:
                    stable_since = time.monotonic()
                elif (time.monotonic() - stable_since) >= 1.0 and current:
                    # Stable non-empty for >=1s. We're done.
                    # If `current` is empty and we've never seen non-
                    # empty, keep waiting -- pyright may still be
                    # cold-starting on the first didOpen of the session.
                    break
            else:
                stable_since = None
                last_snapshot = snapshot
        # Final read. Prefer the latest stable list; fall back to
        # the last non-empty if the server flipped back to [] at the end.
        with srv.diagnostics_lock:
            final = list(srv.diagnostics.get(uri, []))
        if not final and last_non_empty:
            final = last_non_empty
        return {
            "ok": True,
            "path": path,
            "diagnostics": [self._normalize_diagnostic(d) for d in final],
        }

    @staticmethod
    def _normalize_diagnostic(d: dict[str, Any]) -> dict[str, Any]:
        rng = d.get("range") or {}
        start = rng.get("start") or {}
        return {
            "severity": SEVERITY_NAMES.get(d.get("severity"), "info"),
            "message": d.get("message", ""),
            "line": start.get("line", 0),
            "col": start.get("character", 0),
            "code": d.get("code"),
            "source": d.get("source", ""),
        }

    def lsp_hover(
        self, path: str, line: int, col: int,
    ) -> dict[str, Any]:
        srv = self._server_for_path(path)
        if srv is None:
            return {"ok": False,
                    "error": "no LSP server configured for this file"}
        opened = self._open_or_update(srv, path)
        if opened is None:
            return {"ok": False, "error": f"cannot read {path!r}"}
        uri, _ = opened
        # Give the server a moment to index the new doc before asking.
        time.sleep(0.05)
        resp = self._call(srv, "textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": int(line), "character": int(col)},
        })
        if "error" in resp:
            return {"ok": False, "error": str(resp["error"])}
        result = resp.get("result") or {}
        contents = result.get("contents")
        text = self._stringify_hover(contents)
        rng = result.get("range") or {}
        start = rng.get("start") or {}
        return {
            "ok": True, "path": path,
            "text": text,
            "line": start.get("line", line),
            "col": start.get("character", col),
        }

    @staticmethod
    def _stringify_hover(contents: Any) -> str:
        # LSP's `Hover.contents` is the most-overloaded field in the
        # spec: MarkupContent | MarkedString | MarkedString[].
        if contents is None:
            return ""
        if isinstance(contents, str):
            return contents
        if isinstance(contents, dict):
            return str(contents.get("value", ""))
        if isinstance(contents, list):
            parts: list[str] = []
            for c in contents:
                if isinstance(c, str):
                    parts.append(c)
                elif isinstance(c, dict):
                    parts.append(str(c.get("value", "")))
            return "\n\n".join(p for p in parts if p)
        return ""

    def lsp_definition(
        self, path: str, line: int, col: int,
    ) -> dict[str, Any]:
        return self._location_query(
            path, line, col, "textDocument/definition", extra_params={},
        )

    def lsp_references(
        self, path: str, line: int, col: int,
    ) -> dict[str, Any]:
        return self._location_query(
            path, line, col, "textDocument/references",
            extra_params={"context": {"includeDeclaration": True}},
        )

    def _location_query(
        self, path: str, line: int, col: int,
        method: str, extra_params: dict[str, Any],
    ) -> dict[str, Any]:
        srv = self._server_for_path(path)
        if srv is None:
            return {"ok": False,
                    "error": "no LSP server configured for this file"}
        opened = self._open_or_update(srv, path)
        if opened is None:
            return {"ok": False, "error": f"cannot read {path!r}"}
        uri, _ = opened
        time.sleep(0.05)
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": int(line), "character": int(col)},
            **extra_params,
        }
        resp = self._call(srv, method, params)
        if "error" in resp:
            return {"ok": False, "error": str(resp["error"])}
        result = resp.get("result")
        return {
            "ok": True, "path": path,
            "locations": self._normalize_locations(result),
        }

    @staticmethod
    def _normalize_locations(result: Any) -> list[dict[str, Any]]:
        if result is None:
            return []
        items = result if isinstance(result, list) else [result]
        out: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            # LocationLink (linkSupport) and Location have different shapes
            uri = item.get("uri") or item.get("targetUri") or ""
            rng = (item.get("range") or item.get("targetSelectionRange")
                   or item.get("targetRange") or {})
            start = rng.get("start") or {}
            out.append({
                "path": uri_to_path(uri),
                "line": start.get("line", 0),
                "col": start.get("character", 0),
            })
        return out


# Module-level singleton accessed by tools.py (parallel to _MCP_CLIENT).
_LSP_CLIENT: LSPClient | None = None


def set_lsp_client(client: LSPClient | None) -> None:
    global _LSP_CLIENT
    _LSP_CLIENT = client


def get_lsp_client() -> LSPClient | None:
    return _LSP_CLIENT


__all__ = [
    "LSPServer", "LSPClient",
    "path_to_uri", "uri_to_path",
    "set_lsp_client", "get_lsp_client",
]
