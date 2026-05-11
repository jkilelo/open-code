"""Probe: resume loads ALL prior messages with no cap. Token bloat?"""
from __future__ import annotations
import sys, tempfile, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from open_code import db_connect, session_create, message_save, session_resume_for_cwd
from google.genai import types

dbp = Path(tempfile.mkdtemp(prefix="ocbloat-")) / "sessions.db"
c = db_connect(dbp)
sid = session_create(c, "/foo/cwd", "gemini-x", "first task")

# Simulate 200 turns of accumulated history with realistic-size content
for i in range(200):
    user = types.Content(role="user", parts=[types.Part.from_text(text=f"user turn {i}: " + "x"*500)])
    message_save(c, sid, user)
    model = types.Content(role="model", parts=[types.Part.from_text(text=f"model reply {i}: " + "y"*1500)])
    message_save(c, sid, model)

def _chars(hist):
    total = 0
    for m in hist:
        for p in m.parts or []:
            t = getattr(p, "text", None) or ""
            total += len(t)
    return total

# 1) Uncapped (max_messages=0)
sid2, hist0, dropped0 = session_resume_for_cwd(c, "/foo/cwd", max_messages=0)
print(f"[max=0]   loaded {len(hist0)} msgs ({_chars(hist0)//4} est tok), dropped={dropped0}")

# 2) Default cap (80)
sid2, hist80, dropped80 = session_resume_for_cwd(c, "/foo/cwd")
print(f"[default] loaded {len(hist80)} msgs ({_chars(hist80)//4} est tok), dropped={dropped80}")
assert len(hist80) <= 80, f"default cap leaked: got {len(hist80)} > 80"
assert dropped80 == 400 - len(hist80), "dropped count inconsistent"
assert (hist80[0].role or "") == "user", "history must start on user turn"

# 3) Tight cap (10)
sid2, hist10, dropped10 = session_resume_for_cwd(c, "/foo/cwd", max_messages=10)
print(f"[max=10]  loaded {len(hist10)} msgs ({_chars(hist10)//4} est tok), dropped={dropped10}")
assert len(hist10) <= 10
assert (hist10[0].role or "") == "user"

print("OK — resume cap working.")
