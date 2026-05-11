"""Probe: hand-rolled YAML frontmatter parser edge cases.

Real-world skill files won't always be the trivial form.
"""
from __future__ import annotations
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from skills import _parse_frontmatter, _parse_list, _parse_bool

cases = {
    "quoted_value": '---\nname: "review pr"\ndescription: \'unfussy\'\n---\nbody',
    "colon_in_value": "---\nname: foo\ndescription: a tool: handy and short\n---\nbody",
    "list_with_quotes": '---\nname: x\nallowed-tools: ["read_file", "list_dir"]\n---\nbody',
    "list_yaml_dash": "---\nname: x\nallowed-tools:\n  - read_file\n  - list_dir\n---\nbody",
    "multi_line_block": "---\nname: x\ndescription: |\n  multi\n  line\n---\nbody",
    "comment_in_fm": "---\nname: x\n# this is a comment\nfoo: bar\n---\nbody",
    "tabs": "---\n\tname: x\n\tfoo: bar\n---\nbody",
    "empty_frontmatter": "---\n---\nbody",
    "missing_close": "---\nname: x\nbody never sees fence",
}

for label, text in cases.items():
    fm, body = _parse_frontmatter(text)
    print(f"--- {label} ---")
    print(f"  fm   = {fm}")
    print(f"  body = {repr(body)[:60]}")
    print()

print("--- list parsing ---")
print('  ["a","b"]      ->', _parse_list('["a","b"]'))
print("   a, b, c       ->", _parse_list("a, b, c"))
print("  - a  - b       ->", _parse_list("- a  - b"))  # yaml-dash style
print("  (empty)        ->", _parse_list(""))
print()
print("--- bool parsing ---")
for v in ("true", "True", "TRUE", "1", "yes", "on", "false", "no", ""):
    print(f"  {v!r:10} -> {_parse_bool(v)}")
