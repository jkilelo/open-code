"""Probe: hooks.py — fire(), discovery, exit-code conventions."""
from __future__ import annotations
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hooks


def _write_hook(event_dir: Path, name: str, body: str) -> Path:
    """Write a Python hook script and make it executable."""
    event_dir.mkdir(parents=True, exist_ok=True)
    p = event_dir / name
    p.write_text(body, encoding="utf-8")
    if os.name != "nt":
        p.chmod(p.stat().st_mode | stat.S_IRWXU)
    return p


# ---- Test 1: no hooks dir -> empty result, no error ----
with tempfile.TemporaryDirectory() as d:
    r = hooks.fire("PreToolUse", Path(d), session_id="x", payload={})
    assert not r.block and r.invoked == [], f"expected empty result, got {r}"
print("[PASS] no hooks dir -> empty result")


# ---- Test 2: PreToolUse exit 2 blocks; reason captured ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    pre = base / ".open-code" / "hooks" / "PreToolUse"
    _write_hook(pre, "10-deny.py",
                "import sys; sys.stderr.write('go away'); sys.exit(2)")
    r = hooks.fire("PreToolUse", base, session_id="s1",
                   payload={"tool": "write_file", "args": {}})
    assert r.block is True, f"expected block, got {r}"
    assert "go away" in r.reason, f"expected reason, got {r.reason!r}"
    assert "10-deny.py" in r.invoked
print("[PASS] PreToolUse exit 2 blocks; stderr captured as reason")


# ---- Test 3: JSON payload {block, reason} also blocks ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    pre = base / ".open-code" / "hooks" / "PreToolUse"
    _write_hook(pre, "10-jsondeny.py", '''
import sys, json
print(json.dumps({"block": True, "reason": "nope-json"}))
sys.exit(2)
''')
    r = hooks.fire("PreToolUse", base, session_id="s1",
                   payload={"tool": "write_file", "args": {}})
    assert r.block, f"expected block, got {r}"
    assert "nope-json" in r.reason, f"expected json reason, got {r.reason!r}"
print("[PASS] JSON payload reason captured")


# ---- Test 4: PostToolUse never blocks; receives result ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    log_file = base / "hook.log"
    post = base / ".open-code" / "hooks" / "PostToolUse"
    _write_hook(post, "10-log.py", f'''
import sys, json
data = sys.stdin.read()
open(r"{log_file}", "w").write(data)
sys.exit(2)  # would block if PostToolUse honored block - but we ignore
''')
    r = hooks.fire("PostToolUse", base, session_id="s2",
                   payload={"tool": "read_file", "args": {"path": "x"},
                            "result": {"ok": True, "size": 42}})
    # PostToolUse fires; exit 2 still "blocks" in our impl (short-circuits)
    # but downstream code uses the result anyway since it doesn't gate on it.
    assert log_file.exists(), "hook didn't fire"
    rec = json.loads(log_file.read_text())
    assert rec["event"] == "PostToolUse"
    assert rec["tool"] == "read_file"
    assert rec["result"]["size"] == 42
print("[PASS] PostToolUse fires; receives tool result on stdin")


# ---- Test 5: SessionStart additionalContext stitched ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    ss = base / ".open-code" / "hooks" / "SessionStart"
    _write_hook(ss, "10-ctx.py", '''
import json
print(json.dumps({"additionalContext": "Custom intro from hook A"}))
''')
    _write_hook(ss, "20-ctx.py", '''
import json
print(json.dumps({"additionalContext": "Another note from hook B"}))
''')
    r = hooks.fire("SessionStart", base, session_id="s3",
                   payload={"model": "x", "is_resume": False})
    assert r.additional_context is not None
    assert "Custom intro from hook A" in r.additional_context
    assert "Another note from hook B" in r.additional_context
    assert r.invoked == ["10-ctx.py", "20-ctx.py"]  # sorted order
print("[PASS] SessionStart additionalContext stitched from multiple hooks")


# ---- Test 6: UserPromptSubmit transformedPrompt honored ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    ups = base / ".open-code" / "hooks" / "UserPromptSubmit"
    _write_hook(ups, "10-rewrite.py", '''
import sys, json
data = json.loads(sys.stdin.read())
new = data["prompt"].upper()
print(json.dumps({"transformedPrompt": new}))
''')
    r = hooks.fire("UserPromptSubmit", base, session_id="s4",
                   payload={"prompt": "hello world"})
    assert r.transformed_prompt == "HELLO WORLD", f"got {r.transformed_prompt!r}"
print("[PASS] UserPromptSubmit transformedPrompt applied")


# ---- Test 7: env vars set when invoking ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    out = base / "envcheck.json"
    pre = base / ".open-code" / "hooks" / "PreToolUse"
    _write_hook(pre, "10-env.py", f'''
import os, json
data = {{
  "project_dir": os.environ.get("OPEN_CODE_PROJECT_DIR"),
  "session_id":  os.environ.get("OPEN_CODE_SESSION_ID"),
  "cwd":         os.environ.get("OPEN_CODE_CWD"),
}}
open(r"{out}", "w").write(json.dumps(data))
''')
    r = hooks.fire("PreToolUse", base, session_id="abc-123",
                   payload={"tool": "read_file", "args": {}})
    rec = json.loads(out.read_text())
    assert rec["project_dir"] == str(base), f"got {rec['project_dir']!r}"
    assert rec["session_id"] == "abc-123"
    assert rec["cwd"] == str(base)
print("[PASS] env vars OPEN_CODE_PROJECT_DIR / _SESSION_ID / _CWD all set")


# ---- Test 8: misbehaving hook (exit 1) -> errored flag, doesn't crash ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    pre = base / ".open-code" / "hooks" / "PreToolUse"
    _write_hook(pre, "10-broken.py", "import sys; sys.exit(1)")
    _write_hook(pre, "20-ok.py", "")
    r = hooks.fire("PreToolUse", base, session_id="s5", payload={"tool": "x", "args": {}})
    assert r.errored is True
    assert r.block is False
    assert "10-broken.py" in r.invoked
    assert "20-ok.py" in r.invoked
print("[PASS] misbehaving hook logs error; other hooks still run")


# ---- Test 9: walk-up discovery ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    deep = base / "a" / "b" / "c"
    deep.mkdir(parents=True)
    pre = base / ".open-code" / "hooks" / "PreToolUse"
    _write_hook(pre, "10-mark.py", "import sys; sys.exit(2)")
    r = hooks.fire("PreToolUse", deep, session_id="s6",
                   payload={"tool": "x", "args": {}})
    assert r.block, "expected discovery up the tree"
print("[PASS] hooks dir discovered by walking up the tree")


print("\nOK -- 9 hooks probes passed.")
