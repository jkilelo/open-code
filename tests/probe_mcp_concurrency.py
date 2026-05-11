"""Probe: concurrency and lifecycle bugs in the new MCP reader-thread model.

Concerns:
1. `_call` reads-then-increments srv.next_id without a lock. Two threads
   calling _call concurrently could race to claim the same ID.
2. After shutdown(), does the daemon reader thread actually EXIT, or
   does it leak / hang holding stdin?
3. Reader thread is blocked on `for line in proc.stdout`. Does
   srv.reader_stop.is_set() actually stop it, or does the iterator
   only check after the next stdout activity?
"""
from __future__ import annotations
import sys, pathlib, threading, time, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import mcp as mcp_module
from mcp import MCPClient

# Server: ECHOES every request, with reply IDs matching request IDs.
ECHO_SERVER = '''\
import sys, json
while True:
    line = sys.stdin.readline()
    if not line: break
    try:
        req = json.loads(line)
    except Exception:
        continue
    if "id" not in req:
        # notification — ignore
        continue
    if req["method"] == "initialize":
        resp = {"jsonrpc": "2.0", "id": req["id"],
                "result": {"protocolVersion": "2024-11-05",
                           "capabilities": {},
                           "serverInfo": {"name": "echo"}}}
    elif req["method"] == "tools/list":
        resp = {"jsonrpc": "2.0", "id": req["id"],
                "result": {"tools": [
                    {"name": "echo", "description": "echo",
                     "inputSchema": {"type": "object", "properties": {}}}
                ]}}
    elif req["method"] == "tools/call":
        # echo back the id + arguments
        resp = {"jsonrpc": "2.0", "id": req["id"],
                "result": {"content": [{"type": "text",
                                        "text": "echo " + str(req["id"])}],
                           "isError": False}}
    else:
        resp = {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -1, "message": "?"}}
    sys.stdout.write(json.dumps(resp) + "\\n"); sys.stdout.flush()
'''

server_script = pathlib.Path(tempfile.mkstemp(suffix=".py", prefix="echo-")[1])
server_script.write_text(ECHO_SERVER, encoding="utf-8")


# --- Test 1: concurrent _call from two threads ---
client = MCPClient()
client.start_servers({"echo": {"command": sys.executable, "args": [str(server_script)]}})
srv = client.servers["echo"]
print(f"after init: next_id = {srv.next_id}")

# Fire N concurrent call_tool requests from N threads.
N = 8
results = [None] * N
errors = [None] * N
threads_done = threading.Event()
done_count = [0]
lock = threading.Lock()


def worker(i):
    try:
        r = client.call_tool("mcp__echo__echo", {"i": i})
        results[i] = r
    except Exception as exc:
        errors[i] = f"{type(exc).__name__}: {exc}"
    with lock:
        done_count[0] += 1
        if done_count[0] == N:
            threads_done.set()


threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(N)]
for t in threads:
    t.start()

if not threads_done.wait(timeout=15.0):
    print(f"[FAIL] not all threads finished in 15s; done={done_count[0]}/{N}")
    sys.exit(1)

# How many calls succeeded? In single-server _call with no lock, IDs
# may collide, and some calls may pick up the WRONG response.
ok_calls = [r for r in results if r and r.get("ok")]
print(f"successful concurrent calls: {len(ok_calls)}/{N}")
for i, (r, e) in enumerate(zip(results, errors)):
    if e:
        print(f"  [{i}] ERR: {e}")
    elif not r:
        print(f"  [{i}] no result")
    elif not r.get("ok"):
        print(f"  [{i}] FAILED: {r.get('error')}")
    else:
        # The echo server returns "echo <id>". Capture the id and check
        # for uniqueness/collisions.
        txt = r.get("content", [{}])[0].get("text", "")
        print(f"  [{i}] ok content={txt}")

# Note: even if call_tool's results don't crash, the EVIDENCE of race
# is in collisions on next_id. Check the actual id values used:
print(f"\nfinal next_id after {N} concurrent calls + 2 init calls = {srv.next_id}")
# After handshake: initialize=1, tools/list=2, then N concurrent calls
# would consume 3..3+N-1 if no races. If races happen, some calls may
# never see a reply because another thread "stole" their id.

# --- Test 2: shutdown stops reader thread cleanly ---
reader = srv.reader_thread
print(f"\nreader thread alive before shutdown: {reader.is_alive()}")
client.shutdown()
# Give the reader thread a fair chance to notice
reader.join(timeout=3.0)
print(f"reader thread alive after shutdown(3s wait): {reader.is_alive()}")
if reader.is_alive():
    print("[FAIL] reader thread did not exit within 3s of shutdown()")
    sys.exit(1)
print("[PASS] reader thread exited after shutdown")

try: server_script.unlink()
except: pass

# Summary
if errors.count(None) != N:
    print(f"\n[FAIL] {N - errors.count(None)} of {N} concurrent calls threw exceptions")
    sys.exit(1)

# Subtle race check: if all calls returned ok, but multiple THREADS
# might have received the same response if next_id collisions occurred.
# We can't easily detect that without instrumentation, but if ANY call
# silently got a different reply than expected, that's the bug.
print(f"\n[PASS] all {N} concurrent calls completed without exceptions")
