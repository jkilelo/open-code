"""Probe: does the stricter anchor matcher REGRESS legitimate V4A patches?

The fix in patches.py uses `^<anchor>(?:\\b|$)` to refuse ambiguous /
substring matches. But common real-world V4A anchors users would write
include the colon, leading indentation, comments, multi-anchor stacks.

If any of these reasonable patches fail, the fix overcorrected.
"""
from __future__ import annotations
import sys, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import tools, patches
from pathlib import Path

td = pathlib.Path(tempfile.mkdtemp(prefix="oc-legit-"))
tools.CONFIG.cwd = td
results = []


def run_case(label, before_text, patch_text, must_apply_to_match):
    fn = td / f"case_{label}.py"
    fn.write_text(before_text, encoding="utf-8")
    r = patches.apply_patch(patch_text)
    after = fn.read_text(encoding="utf-8") if fn.exists() else "<missing>"
    ok = r["ok"]
    body_matched = must_apply_to_match in after
    status = "PASS" if (ok and body_matched) else "FAIL"
    print(f"[{status}] {label}: ok={ok} body_has_marker={body_matched}")
    if not ok:
        print(f"    error: {r.get('error', r)}")
    else:
        print(f"    applied: {r.get('applied')}")
    results.append((label, status))


# Case A: anchor with colon (class)
run_case(
    "anchor_with_colon",
    "class MyClass:\n    def method(self):\n        return 1\n",
    """\
*** Begin Patch
*** Update File: case_anchor_with_colon.py
@@ class MyClass:
     def method(self):
-        return 1
+        return 99
*** End Patch
""",
    "return 99",
)

# Case B: anchor includes leading indentation (4 spaces)
# Note: V4A spec says anchors are written without leading ws — the
# parser strips it. But what if a user writes it WITH leading indent?
run_case(
    "anchor_leading_indent",
    "class X:\n    def alpha(self):\n        return 1\n    def beta(self):\n        return 2\n",
    """\
*** Begin Patch
*** Update File: case_anchor_leading_indent.py
@@     def beta(self):
-        return 2
+        return 22
*** End Patch
""",
    "return 22",
)

# Case C: anchor is a comment header
run_case(
    "anchor_comment_header",
    "x = 1\n\n# === SECTION B ===\ndef impl_b():\n    return 1\n",
    """\
*** Begin Patch
*** Update File: case_anchor_comment_header.py
@@ # === SECTION B ===
 def impl_b():
-    return 1
+    return 999
*** End Patch
""",
    "return 999",
)

# Case D: stacked anchors (class + method)
run_case(
    "anchor_stacked",
    "class A:\n    def m(self):\n        return 1\n\nclass B:\n    def m(self):\n        return 2\n",
    """\
*** Begin Patch
*** Update File: case_anchor_stacked.py
@@ class B:
@@ def m(self):
-        return 2
+        return 77
*** End Patch
""",
    "return 77",
)

# Case E: anchor with full def signature (paren+args)
run_case(
    "anchor_full_def",
    "def greet(name):\n    return 'hi ' + name\n\ndef greet_fancy(name):\n    return 'salutations ' + name\n",
    """\
*** Begin Patch
*** Update File: case_anchor_full_def.py
@@ def greet(name):
-    return 'hi ' + name
+    return 'hello ' + name
*** End Patch
""",
    "return 'hello ' + name",
)

# Case F: anchor matching at end of line (e.g. variable assignment)
run_case(
    "anchor_eol",
    "VERSION = '0.14.0'\nVERSION_BUILD = '0.14.0-rc1'\n",
    """\
*** Begin Patch
*** Update File: case_anchor_eol.py
@@ VERSION = '0.14.0'
-VERSION = '0.14.0'
+VERSION = '0.14.1'
*** End Patch
""",
    "VERSION = '0.14.1'",
)

# Case G: anchor `def b` against `def b():` then `def b_helper`.
# This is exactly the case that v0.14.1 was supposed to NOT regress.
run_case(
    "anchor_short_def_b",
    "def a():\n    return 1\n\ndef b():\n    return 2\n",
    """\
*** Begin Patch
*** Update File: case_anchor_short_def_b.py
@@ def b
-    return 2
+    return 99
*** End Patch
""",
    "return 99",
)

# Case H: realistic patch from open-code's own README — typical code edit
run_case(
    "typical_function_edit",
    "def compute(x, y):\n    z = x + y\n    return z\n",
    """\
*** Begin Patch
*** Update File: case_typical_function_edit.py
@@ def compute(x, y):
     z = x + y
-    return z
+    return z * 2
*** End Patch
""",
    "return z * 2",
)


fails = [r for r in results if r[1] == "FAIL"]
print(f"\n=== {len(results) - len(fails)}/{len(results)} legitimate-patch cases passed ===")
if fails:
    print("FAILED cases:", [f[0] for f in fails])
    sys.exit(1)
