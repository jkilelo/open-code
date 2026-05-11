"""Probe: model fallback chain. When the primary 404s, we fall through."""
from __future__ import annotations
import os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load API key
try:
    from dotenv import load_dotenv
    load_dotenv(Path(r"C:\Users\kleiy\OneDrive\Desktop\ai_agents\.env"))
except ImportError:
    pass

import open_code as oc

# === Test 1: _is_model_unavailable_error classifier ===
print("=== _is_model_unavailable_error ===")
cases = [
    ("404 Not Found: models/foo", True),
    ("model not found", True),
    ("Model is deprecated", True),
    ("invalid model name", True),
    ("This model is unavailable", True),
    ("rate limit exceeded", False),
    ("permission denied", False),
    ("quota exceeded", False),
    ("authentication failed", False),
    ("Connection timeout", False),
]
for msg, want in cases:
    got = oc._is_model_unavailable_error(Exception(msg))
    status = "OK " if got == want else "WRONG"
    print(f"  [{status}] msg={msg!r}  want={want} got={got}")

# === Test 2: live run with a deliberately-bogus primary model ===
api_key = os.environ.get("GEMINI_API_KEY", "").strip()
if not api_key:
    print("\nNO GEMINI_API_KEY -- skipping live fallback test")
    sys.exit(0)

print("\n=== Live fallback with bogus primary ===")
from sessions import SessionStore
tmp = Path(tempfile.mkdtemp(prefix="ocfallback-"))
oc.CONFIG.cwd = tmp
import os as _os
_os.chdir(tmp)

store = SessionStore(tmp)
session = store.create(str(tmp), "gemini-bogus-99-nonexistent", "test")

code, metrics = oc.run_loop(
    task="reply with the single word PONG",
    model="gemini-bogus-99-nonexistent",
    api_key=api_key,
    max_iterations=3,
    store=store,
    session=session,
    initial_history=[],
    verbose=True,
    stream=False,
)
print(f"\nexit_code={code} final_model={metrics['model']!r}")
assert code == 0, f"fallback did not recover: exit={code}"
assert metrics["model"] != "gemini-bogus-99-nonexistent", "model did not advance"
assert metrics["model"] in oc.MODEL_FALLBACK_CHAIN, f"unexpected model: {metrics['model']!r}"
print(f"OK -- fell back from bogus -> {metrics['model']!r}")
