"""Probe: does apply_patch's anchor matching ever apply to the wrong site?

Risks:
1. Anchor matcher uses substring `in` match (line 235 in patches.py),
   not just exact equality. A short anchor like `@@ def foo` would
   match `def foo` AND `def foo_helper` AND `def something_foo_bar`.
2. The rstrip-tolerant fallback (line 254-260) breaks on FIRST match
   instead of collecting all matches, so an ambiguity check is bypassed.
"""
from __future__ import annotations
import sys, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import os
from pathlib import Path
import tools, patches

# Set up an isolated CWD so the sandbox lets us write.
td = pathlib.Path(tempfile.mkdtemp(prefix="oc-misanchor-"))
tools.CONFIG.cwd = td

# Case 1: Substring anchor match — a short anchor matches MULTIPLE defs
# but only the first is considered. The hunk applies at the wrong place.
target = td / "evil.py"
target.write_text(
    "def foo_helper():\n"
    "    return 1\n"
    "\n"
    "def foo():\n"
    "    return 2\n",
    encoding="utf-8",
)

patch = """\
*** Begin Patch
*** Update File: evil.py
@@ def foo
     return 1
+    # MUTATED
*** End Patch
"""
# Intent of `@@ def foo` is plausibly the `def foo():` line, but
# `def foo_helper():` ALSO contains `def foo` as a substring.
# The anchor matcher in patches.py line 235 uses substring `in`.

result = patches.apply_patch(patch)
print("CASE 1: ambiguous anchor 'def foo' (matches BOTH `def foo_helper` AND `def foo`):")
print(" ", result)
after = target.read_text(encoding="utf-8")
print(" after =", repr(after))
# The bug was: silent miswrite into foo_helper. The fix: refuse cleanly.
assert not result["ok"], (
    f"CASE 1 regression: ambiguous anchor produced ok=True; result={result}"
)
assert "# MUTATED" not in after, (
    f"CASE 1 regression: '# MUTATED' was written despite ambiguous anchor"
)
print("  [PASS] Case 1: ambiguous anchor refused")

# Case 2: rstrip-fallback false positive
target2 = td / "ws.py"
target2.write_text(
    "x = 1   \n"        # trailing whitespace
    "x = 1\n"           # exact form
    "y = 2\n",
    encoding="utf-8",
)
# Patch supplies "x = 1" (no trailing ws) for the `before` line.
# The strict pass finds ONE exact match. But suppose we craft a `before`
# pattern that strict-matches NONE but rstrip-matches MULTIPLE.
target3 = td / "ws2.py"
target3.write_text(
    "x = 1   \n"
    "x = 1\t\n"
    "y = 2\n",
    encoding="utf-8",
)
patch2 = """\
*** Begin Patch
*** Update File: ws2.py
 x = 1
+# applied
*** End Patch
"""
# both lines `x = 1   ` and `x = 1\t` rstrip to `x = 1`. With the
# fallback's `break`, the first one wins silently.
result2 = patches.apply_patch(patch2)
print()
print("CASE 2: rstrip-fallback when both lines rstrip-equal:")
print(" ", result2)
after2 = target3.read_text(encoding="utf-8")
print(" after =", repr(after2))
assert not result2["ok"], (
    f"CASE 2 regression: ambiguous rstrip-fallback produced ok=True; result={result2}"
)
assert "# applied" not in after2, (
    f"CASE 2 regression: '# applied' was written despite ambiguous match"
)
print("  [PASS] Case 2: ambiguous rstrip-fallback refused")
print("\nOK -- both apply_patch misanchor cases correctly refused.")
