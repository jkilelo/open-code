"""Probe: V4A apply_patch -- parser + applier edge cases."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import patches
from tools import CONFIG


# ---- Test 1: parser handles Add / Delete / Update / Move ----
patch = """*** Begin Patch
*** Add File: foo.py
+print('hi')
+# end
*** Delete File: old.txt
*** Update File: bar.py
*** Move to: baz.py
@@ def hello
-    return 1
+    return 2
*** End Patch
"""
actions = patches.parse_patch(patch)
ops = [(a.op, a.path, a.move_to) for a in actions]
assert ops == [
    ("add", "foo.py", None),
    ("delete", "old.txt", None),
    ("update", "bar.py", "baz.py"),
], f"got {ops}"
assert actions[0].content == "print('hi')\n# end\n", repr(actions[0].content)
upd = actions[2]
assert len(upd.hunks) == 1
hunk = upd.hunks[0]
assert hunk.anchors == ["def hello"], hunk.anchors
assert hunk.lines == [("del", "    return 1"), ("add", "    return 2")], hunk.lines
print("[PASS] parser handles add / delete / update + move / anchored hunk")


# ---- Test 2: missing Begin/End -> PatchParseError ----
try:
    patches.parse_patch("not a patch")
except patches.PatchParseError:
    pass
else:
    raise AssertionError("expected PatchParseError")
print("[PASS] missing Begin/End markers raise PatchParseError")


# ---- Test 3: Add File creates a new file ----
with tempfile.TemporaryDirectory() as d:
    CONFIG.cwd = Path(d).resolve()
    CONFIG.allow_outside_cwd = False
    p = """*** Begin Patch
*** Add File: hello.py
+print("hi")
*** End Patch
"""
    r = patches.apply_patch(p)
    assert r["ok"], r
    assert (CONFIG.cwd / "hello.py").read_text() == 'print("hi")\n'
print("[PASS] Add File creates file")


# ---- Test 4: Add File refuses if path exists ----
with tempfile.TemporaryDirectory() as d:
    CONFIG.cwd = Path(d).resolve()
    (CONFIG.cwd / "exists.txt").write_text("already here", encoding="utf-8")
    p = """*** Begin Patch
*** Add File: exists.txt
+new content
*** End Patch
"""
    r = patches.apply_patch(p)
    assert not r["ok"]
    assert "already exists" in r["error"]
print("[PASS] Add File refuses to overwrite existing path")


# ---- Test 5: Update File with anchor finds + applies ----
with tempfile.TemporaryDirectory() as d:
    CONFIG.cwd = Path(d).resolve()
    (CONFIG.cwd / "x.py").write_text(
        "def a():\n    return 1\n\ndef b():\n    return 2\n", encoding="utf-8"
    )
    p = """*** Begin Patch
*** Update File: x.py
@@ def b
-    return 2
+    return 99
*** End Patch
"""
    r = patches.apply_patch(p)
    assert r["ok"], r
    text = (CONFIG.cwd / "x.py").read_text()
    assert "return 99" in text
    assert "return 1" in text  # the OTHER function unchanged
    assert "return 2" not in text
print("[PASS] Update File with anchor preserves untouched code")


# ---- Test 6: Update File errors when anchor not found ----
with tempfile.TemporaryDirectory() as d:
    CONFIG.cwd = Path(d).resolve()
    (CONFIG.cwd / "x.py").write_text("def a():\n    pass\n", encoding="utf-8")
    p = """*** Begin Patch
*** Update File: x.py
@@ def nonexistent
-    pass
+    return 0
*** End Patch
"""
    r = patches.apply_patch(p)
    assert not r["ok"]
    assert "anchor not found" in r["error"]
print("[PASS] Update File reports missing anchor")


# ---- Test 7: Update + Move renames atomically ----
with tempfile.TemporaryDirectory() as d:
    CONFIG.cwd = Path(d).resolve()
    (CONFIG.cwd / "old.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    p = """*** Begin Patch
*** Update File: old.py
*** Move to: new.py
@@ def f
-    return 1
+    return 2
*** End Patch
"""
    r = patches.apply_patch(p)
    assert r["ok"], r
    assert not (CONFIG.cwd / "old.py").exists()
    assert (CONFIG.cwd / "new.py").read_text() == "def f():\n    return 2\n"
print("[PASS] Update + Move renames after applying hunks")


# ---- Test 8: Delete File ----
with tempfile.TemporaryDirectory() as d:
    CONFIG.cwd = Path(d).resolve()
    (CONFIG.cwd / "x.txt").write_text("bye", encoding="utf-8")
    p = """*** Begin Patch
*** Delete File: x.txt
*** End Patch
"""
    r = patches.apply_patch(p)
    assert r["ok"], r
    assert not (CONFIG.cwd / "x.txt").exists()
print("[PASS] Delete File removes the target")


# ---- Test 9: Path sandbox refuses paths outside CWD ----
with tempfile.TemporaryDirectory() as d:
    with tempfile.TemporaryDirectory() as outside:
        CONFIG.cwd = Path(d).resolve()
        CONFIG.allow_outside_cwd = False
        escape = Path(outside).resolve() / "escape.py"
        p = f"""*** Begin Patch
*** Add File: {escape}
+pwned
*** End Patch
"""
        r = patches.apply_patch(p)
        assert not r["ok"]
        assert "outside CWD" in r.get("failed", [{}])[0].get("error", "") \
               or "outside CWD" in r.get("error", "")
print("[PASS] sandbox: Add File outside CWD refused")


# ---- Test 10: Tool declaration shape (lives in tools.py) ----
from tools import APPLY_PATCH_TOOL_DECLARATION
d = APPLY_PATCH_TOOL_DECLARATION
assert d["name"] == "apply_patch"
assert "patch" in d["parameters"]["properties"]
assert d["parameters"]["required"] == ["patch"]
print("[PASS] APPLY_PATCH_TOOL_DECLARATION shape (sourced from tools.py)")


print("\nOK -- 10 apply_patch probes passed.")
