"""Probe: an MCP server that never responds hangs the agent loop forever.

We spawn a tiny Python "server" that reads stdin and never writes
stdout. The MCPClient._call should time out — but it doesn't, because
CALL_TIMEOUT_SECS is defined but never used.

Verification: we run call_tool() in a thread with a 5-second join.
If it returns within 5s, the timeout works. If the thread is still
alive at 5s, the bug is confirmed.
"""
from __future__ import annotations
import sys, pathlib, threading, time, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import mcp as mcp_module
from mcp import MCPClient, MCPServer
import subprocess

# Force the per-call timeout low so this probe doesn't wait 60s.
mcp_module.CALL_TIMEOUT_SECS = 3.0

# Tiny silent server: reads stdin forever, never writes stdout
SILENT_SERVER = """\
import sys, json, os
# Read the initialize request and just acknowledge so handshake passes
line = sys.stdin.readline()
req = json.loads(line)
resp = {"jsonrpc": "2.0", "id": req["id"],
        "result": {"protocolVersion": "2024-11-05",
                   "capabilities": {}, "serverInfo": {"name": "silent"}}}
sys.stdout.write(json.dumps(resp) + "\\n"); sys.stdout.flush()
# Drain notifications/initialized
sys.stdin.readline()
# tools/list — give one tool
line = sys.stdin.readline()
req = json.loads(line)
resp = {"jsonrpc": "2.0", "id": req["id"],
        "result": {"tools": [{"name": "hang", "description": "hangs",
                              "inputSchema": {"type": "object", "properties": {}}}]}}
sys.stdout.write(json.dumps(resp) + "\\n"); sys.stdout.flush()
# Now: a tools/call arrives. Read it but NEVER respond.
while True:
    line = sys.stdin.readline()
    if not line:
        break
"""

server_script = pathlib.Path(tempfile.mkstemp(suffix=".py", prefix="silent-")[1])
server_script.write_text(SILENT_SERVER, encoding="utf-8")

client = MCPClient()
client.start_servers({"silent": {"command": sys.executable, "args": [str(server_script)]}})

print(f"servers: {list(client.servers.keys())}")
print(f"tools: {[t['name'] for s in client.servers.values() for t in s.tools]}")

# Now call_tool — should it hang?
hang_done = threading.Event()
hang_result = []

def call_it():
    try:
        r = client.call_tool("mcp__silent__hang", {})
    except Exception as exc:
        r = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    hang_result.append(r)
    hang_done.set()

t = threading.Thread(target=call_it, daemon=True)
t.start()

# Wait up to 8 seconds. If the call returns, timeout enforcement works.
returned = hang_done.wait(timeout=8.0)

client.shutdown()
try: server_script.unlink()
except: pass

if not returned:
    print("[FAIL] call did NOT return within 8s; CALL_TIMEOUT_SECS not enforced")
    sys.exit(1)

result = hang_result[0]
assert not result["ok"], f"silent-server call should have failed; got {result}"
assert "timed out" in result.get("error", "").lower() or "TimeoutError" in result.get("error", ""), (
    f"expected timeout error; got {result}"
)
print(f"[PASS] call returned with timeout error: {result['error'][:80]}")
print("OK -- MCP _call now respects CALL_TIMEOUT_SECS.")
