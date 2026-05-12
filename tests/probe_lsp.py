"""Probe: lsp.py -- Content-Length-framed JSON-RPC against a mock LSP server.

In-process mock server (see _mock_lsp_server.py spawned below)
handles initialize, didOpen (publishing one fake diagnostic),
hover, definition, references. Verifies the LSPClient drives the
correct request/response cycle and routes publishDiagnostics
notifications back to the lsp_diagnostics() waiter.
"""
from __future__ import annotations
import json
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lsp import LSPClient, path_to_uri, uri_to_path


# ---- Test 1: path <-> uri round-trip ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    p = base / "sub" / "file.py"
    p.parent.mkdir()
    p.write_text("print('hi')\n", encoding="utf-8")
    uri = path_to_uri(str(p))
    assert uri.startswith("file://"), f"got: {uri}"
    back = Path(uri_to_path(uri)).resolve()
    assert back == p.resolve(), f"round-trip lost the path: {p} -> {uri} -> {back}"
print("[PASS] path <-> uri round-trip (Windows + POSIX shapes)")


# ---- Test 2: disabled -> tools return helpful ok=False ----
from tools import tool_lsp_diagnostics, tool_lsp_hover
from lsp import set_lsp_client
set_lsp_client(None)
r = tool_lsp_diagnostics("anything.py")
assert not r["ok"] and "LSP is not enabled" in r["error"], r
r = tool_lsp_hover("anything.py", 0, 0)
assert not r["ok"], r
print("[PASS] tools return helpful error when LSP not configured")


# ---- Test 3: live handshake + diagnostics + hover + def + refs against mock ----
mock_src = textwrap.dedent('''\
"""Mock LSP server: Content-Length-framed JSON-RPC over stdio.

Handles initialize, didOpen (publishes one diagnostic), hover,
definition, references. Just enough surface for probe_lsp.py.
"""
from __future__ import annotations
import json
import sys


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        s = line.decode("ascii", errors="replace").rstrip("\\r\\n")
        if not s:
            break
        if ":" in s:
            k, v = s.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    n = int(headers.get("content-length", "0"))
    body = b""
    while len(body) < n:
        chunk = sys.stdin.buffer.read(n - len(body))
        if not chunk:
            return None
        body += chunk
    return json.loads(body.decode("utf-8"))


def write_message(msg):
    body = json.dumps(msg).encode("utf-8")
    header = f"Content-Length: {len(body)}\\r\\n\\r\\n".encode("ascii")
    sys.stdout.buffer.write(header + body)
    sys.stdout.buffer.flush()


def main():
    while True:
        msg = read_message()
        if msg is None:
            return
        method = msg.get("method")
        msg_id = msg.get("id")
        if method == "initialize":
            write_message({"jsonrpc": "2.0", "id": msg_id,
                           "result": {"capabilities": {
                               "hoverProvider": True,
                               "definitionProvider": True,
                               "referencesProvider": True,
                           }}})
        elif method == "initialized":
            pass
        elif method == "textDocument/didOpen":
            uri = msg["params"]["textDocument"]["uri"]
            # Publish one fake diagnostic immediately.
            write_message({
                "jsonrpc": "2.0",
                "method": "textDocument/publishDiagnostics",
                "params": {
                    "uri": uri,
                    "diagnostics": [{
                        "range": {"start": {"line": 0, "character": 0},
                                  "end":   {"line": 0, "character": 5}},
                        "severity": 1,
                        "code": "E001",
                        "source": "mock",
                        "message": "fake error from mock LSP",
                    }],
                },
            })
        elif method == "textDocument/didChange":
            uri = msg["params"]["textDocument"]["uri"]
            write_message({
                "jsonrpc": "2.0",
                "method": "textDocument/publishDiagnostics",
                "params": {"uri": uri, "diagnostics": []},
            })
        elif method == "textDocument/hover":
            uri = msg["params"]["textDocument"]["uri"]
            pos = msg["params"]["position"]
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": {
                "contents": {
                    "kind": "markdown",
                    "value": f"hover at {pos['line']}:{pos['character']}",
                },
                "range": {
                    "start": {"line": pos["line"], "character": pos["character"]},
                    "end":   {"line": pos["line"], "character": pos["character"] + 3},
                },
            }})
        elif method == "textDocument/definition":
            uri = msg["params"]["textDocument"]["uri"]
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": [{
                "uri": uri,
                "range": {"start": {"line": 7, "character": 4},
                          "end":   {"line": 7, "character": 9}},
            }]})
        elif method == "textDocument/references":
            uri = msg["params"]["textDocument"]["uri"]
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": [
                {"uri": uri,
                 "range": {"start": {"line": 1, "character": 0},
                           "end":   {"line": 1, "character": 5}}},
                {"uri": uri,
                 "range": {"start": {"line": 4, "character": 2},
                           "end":   {"line": 4, "character": 7}}},
            ]})
        elif method == "shutdown":
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": None})
        elif method == "exit":
            return


if __name__ == "__main__":
    main()
''')

with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    mock_path = base / "_mock_lsp_server.py"
    mock_path.write_text(mock_src, encoding="utf-8")

    target = base / "thing.py"
    target.write_text("x = 1\nprint(x)\n", encoding="utf-8")

    client = LSPClient(cwd=base)
    client.configure({
        "enabled": True,
        "servers": {
            "python": {
                "command": sys.executable,
                "args": [str(mock_path)],
                "file_patterns": ["*.py"],
            },
        },
    })

    # diagnostics: drives initialize + didOpen + waits for publishDiagnostics
    r = client.lsp_diagnostics(str(target))
    assert r["ok"], r
    assert len(r["diagnostics"]) == 1, r
    d0 = r["diagnostics"][0]
    assert d0["severity"] == "error", d0
    assert "fake error" in d0["message"], d0
    assert d0["line"] == 0 and d0["col"] == 0, d0
    assert d0["code"] == "E001" and d0["source"] == "mock", d0
    print("[PASS] lsp_diagnostics: initialize + didOpen + publishDiagnostics route correctly")

    # hover at position (1, 6) -- middle of `print(x)`
    r = client.lsp_hover(str(target), 1, 6)
    assert r["ok"], r
    assert "hover at 1:6" in r["text"], r
    print(f"[PASS] lsp_hover: returned {r['text']!r}")

    # definition
    r = client.lsp_definition(str(target), 1, 6)
    assert r["ok"], r
    assert len(r["locations"]) == 1, r
    assert r["locations"][0]["line"] == 7, r
    print(f"[PASS] lsp_definition: {r['locations']}")

    # references
    r = client.lsp_references(str(target), 1, 6)
    assert r["ok"], r
    assert len(r["locations"]) == 2, r
    print(f"[PASS] lsp_references: {len(r['locations'])} locations")

    client.shutdown()
print("[PASS] live handshake + 4 LSP queries against mock server")


# ---- Test 4: tool dispatch via TOOL_FUNCTIONS table ----
import tools as TOOLS
assert "lsp_diagnostics" in TOOLS.TOOL_FUNCTIONS
assert "lsp_hover" in TOOLS.TOOL_FUNCTIONS
assert "lsp_definition" in TOOLS.TOOL_FUNCTIONS
assert "lsp_references" in TOOLS.TOOL_FUNCTIONS
names = [d["name"] for d in TOOLS.TOOL_DECLARATIONS]
for n in ("lsp_diagnostics", "lsp_hover", "lsp_definition", "lsp_references"):
    assert n in names, f"{n} missing from TOOL_DECLARATIONS"
print("[PASS] all 4 LSP tools registered in TOOL_FUNCTIONS + TOOL_DECLARATIONS")


# ---- Test 5: no-server-matches-file -> graceful ok=False ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    client = LSPClient(cwd=base)
    client.configure({
        "enabled": True,
        "servers": {
            "python": {
                "command": sys.executable,
                "args": ["-c", "import sys; sys.exit(0)"],
                "file_patterns": ["*.py"],
            },
        },
    })
    r = client.lsp_diagnostics("foo.rs")  # no rust server configured
    assert not r["ok"], r
    assert "no LSP server" in r["error"], r
print("[PASS] file with no matching server returns helpful error")


print("\nOK -- LSP probes passed.")
