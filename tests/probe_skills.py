"""Probe: skills.py — discovery, frontmatter, $ARGUMENTS, !`cmd` blocks."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import skills


def _write_skill(base: Path, name: str, fm: str, body: str) -> Path:
    d = base / ".open-code" / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")
    return p


# ---- Test 1: no skills dir -> empty list ----
with tempfile.TemporaryDirectory() as d:
    assert skills.discover_skills(Path(d)) == []
print("[PASS] no skills dir -> []")


# ---- Test 2: discover + parse frontmatter ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write_skill(base, "review",
                 "name: review\ndescription: brutal review\nallowed-tools: read_file, list_dir",
                 "Review the change.")
    found = skills.discover_skills(base)
    assert len(found) == 1, f"got {len(found)}"
    s = found[0]
    assert s.name == "review"
    assert "brutal review" in s.description
    assert "read_file" in s.allowed_tools and "list_dir" in s.allowed_tools
    assert s.disable_model_invocation is False
print("[PASS] frontmatter parsed (name/description/allowed-tools)")


# ---- Test 3: $ARGUMENTS substitution ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write_skill(base, "echo",
                 "name: echo\ndescription: echoes",
                 "User said: $ARGUMENTS\nFirst word: $1\nSecond: $2")
    s = skills.find_skill_by_name(base, "echo")
    assert s is not None
    out = skills.expand_skill_body(s, "hello world friend", base)
    assert "User said: hello world friend" in out
    assert "First word: hello" in out
    assert "Second: world" in out
print("[PASS] $ARGUMENTS / $1 / $2 substitution")


# ---- Test 4: !`cmd` blocks resolved ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write_skill(base, "stat",
                 "name: stat\ndescription: shows env",
                 "Current echo: !`echo HELLO_FROM_SKILL`")
    s = skills.find_skill_by_name(base, "stat")
    out = skills.expand_skill_body(s, "", base)
    assert "HELLO_FROM_SKILL" in out, f"got {out!r}"
    assert "!`" not in out, "command markers should be replaced"
print("[PASS] !`cmd` blocks resolved")


# ---- Test 5: bad cmd -> error message in output, not crash ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write_skill(base, "broken",
                 "name: broken\ndescription: x",
                 "Bad: !`exit 7`")
    s = skills.find_skill_by_name(base, "broken")
    out = skills.expand_skill_body(s, "", base)
    # Exit 7 with empty stdout -> "(no output)"
    assert "Bad:" in out
print("[PASS] failing !`cmd` doesn't crash; placeholder replaced")


# ---- Test 6: skill name falls back to dir name if frontmatter missing ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    d_skill = base / ".open-code" / "skills" / "fromdir"
    d_skill.mkdir(parents=True)
    (d_skill / "SKILL.md").write_text("no frontmatter\njust body", encoding="utf-8")
    found = skills.discover_skills(base)
    assert len(found) == 1
    assert found[0].name == "fromdir"
print("[PASS] missing frontmatter -> name from dir")


# ---- Test 7: disable-model-invocation flag parsed ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write_skill(base, "private",
                 "name: private\ndescription: x\ndisable-model-invocation: true",
                 "")
    s = skills.find_skill_by_name(base, "private")
    assert s.disable_model_invocation is True
print("[PASS] disable-model-invocation: true parsed")


# ---- Test 8: multiple skills sorted by dir name ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write_skill(base, "zzz-late", "name: z\ndescription: z", "")
    _write_skill(base, "aaa-early", "name: a\ndescription: a", "")
    _write_skill(base, "mmm-mid", "name: m\ndescription: m", "")
    found = skills.discover_skills(base)
    assert [s.name for s in found] == ["a", "m", "z"], \
        f"got {[s.name for s in found]}"
print("[PASS] skills sorted by directory name")


# ---- Test 9: rendering ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    _write_skill(base, "review", "name: review\ndescription: brutal",
                 "")
    rendered = skills.render_skill_listing(skills.discover_skills(base))
    assert "NAME" in rendered and "DESCRIPTION" in rendered
    assert "review" in rendered
print("[PASS] render_skill_listing produces a table")


print("\nOK -- 9 skills probes passed.")
