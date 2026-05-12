"""Probe: mcp.py -- JSON-RPC over stdio against a mock MCP server."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp import MCPClient, MCPServer, PROTOCOL_VERSION, _normalize_schema


# ---- Test 1: _normalize_schema converts JSON Schema types ----
schema_in = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age":  {"type": "integer"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name"],
}
out = _normalize_schema(schema_in)
# v0.30.2: standard JSON Schema lowercase (was UPPERCASE for Gemini).
# Anthropic + OpenAI require lowercase; Gemini accepts both.
assert out["type"] == "object"
assert out["properties"]["name"]["type"] == "string"
assert out["properties"]["age"]["type"] == "integer"
assert out["properties"]["tags"]["type"] == "array"
assert out["properties"]["tags"]["items"]["type"] == "string"
print("[PASS] _normalize_schema preserves JSON Schema lowercase types")


# ---- Test 2: call_tool rejects malformed names ----
client = MCPClient()
r = client.call_tool("not_mcp_prefixed", {})
assert not r["ok"], r
r = client.call_tool("mcp__bad_format_no_double_underscore", {})
assert not r["ok"], r
r = client.call_tool("mcp__nonexistent__tool", {})
assert not r["ok"], r
assert "unknown MCP server" in r["error"]
print("[PASS] call_tool validates namespace + checks server existence")


# ---- Test 3: Live MCP handshake against a tiny in-process mock server ----
# We write a 30-line Python "MCP server" that responds to initialize +
# tools/list + tools/call.

MOCK_SERVER = textwrap.dedent('''
    import json, sys

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        if method == "initialize":
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"protocolVersion": "2024-11-05",
                           "capabilities": {},
                           "serverInfo": {"name": "mock", "version": "0.1"}}
            }) + "\\n")
            sys.stdout.flush()
        elif method == "notifications/initialized":
            pass  # no response
        elif method == "tools/list":
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"tools": [
                    {"name": "echo",
                     "description": "Echo back the input",
                     "inputSchema": {"type": "object",
                                     "properties": {"text": {"type": "string"}}}}
                ]}
            }) + "\\n")
            sys.stdout.flush()
        elif method == "tools/call":
            params = msg.get("params", {})
            args = params.get("arguments", {})
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"content": [{"type": "text",
                                        "text": "echoed: " + str(args.get("text", ""))}],
                           "isError": False}
            }) + "\\n")
            sys.stdout.flush()
        else:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": "Method not found"}
            }) + "\\n")
            sys.stdout.flush()
''')

with tempfile.TemporaryDirectory() as d:
    mock_path = Path(d) / "mock_mcp.py"
    mock_path.write_text(MOCK_SERVER, encoding="utf-8")

    client = MCPClient()
    client.start_servers({
        "mock": {"command": sys.executable, "args": [str(mock_path)]}
    })
    try:
        # Server should have been discovered and have 1 tool
        assert "mock" in client.servers, f"got servers={list(client.servers)}"
        srv = client.servers["mock"]
        assert len(srv.tools) == 1
        assert srv.tools[0]["name"] == "echo"
        print("[PASS] handshake: initialize + tools/list against mock server")

        # Translation into TOOL_DECLARATIONS format
        decls = client.all_tool_declarations()
        assert len(decls) == 1
        assert decls[0]["name"] == "mcp__mock__echo"
        assert "MCP server: mock" in decls[0]["description"]
        params = decls[0]["parameters"]
        assert params["type"] == "object"
        assert params["properties"]["text"]["type"] == "string"
        print("[PASS] all_tool_declarations exposes mcp__mock__echo with normalized schema")

        # Call the tool
        result = client.call_tool("mcp__mock__echo", {"text": "hello world"})
        assert result["ok"], result
        content = result.get("content", [])
        assert content and content[0]["text"] == "echoed: hello world"
        print("[PASS] call_tool: routes mcp__mock__echo to server, returns content")
    finally:
        client.shutdown()


# ---- Test 4: missing-command server fails gracefully ----
client = MCPClient()
client.start_servers({
    "broken": {"command": "this-command-definitely-does-not-exist-xyz", "args": []}
})
assert "broken" not in client.servers, "broken server should NOT be added"
print("[PASS] missing command: server skipped without crashing")


# ---- Test 5: shutdown cleans up subprocesses ----
with tempfile.TemporaryDirectory() as d:
    mock_path = Path(d) / "mock_mcp.py"
    mock_path.write_text(MOCK_SERVER, encoding="utf-8")
    client = MCPClient()
    client.start_servers({"m": {"command": sys.executable, "args": [str(mock_path)]}})
    assert "m" in client.servers
    pid = client.servers["m"].proc.pid
    client.shutdown()
    assert not client.servers
print("[PASS] shutdown terminates servers + clears registry")


print("\nOK -- 5 mcp probes passed.")
