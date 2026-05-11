"""Probe: every tracked source/doc file is pure ASCII.

The user's hard requirement is "100% no encoding issues in any
platform." Mojibake bit us once (UTF-8 misread as cp1252 then
re-encoded into the file). Even properly-encoded UTF-8 isn't safe
on every terminal/code-page combination -- Windows console cp1252,
older `less`/`more` viewers, non-UTF-8 SSH sessions all fail to
render emoji or special punctuation.

This probe enforces pure ASCII across every file extension that
ships in the repo: `.py`, `.md`, `.json`, `.txt`, `.sh`, plus
hook scripts under `.claude/`.

If you genuinely need a special character (e.g. in a test that
verifies UTF-8 handling), exempt the file by adding its path to
`ALLOW_NON_ASCII`.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOW_NON_ASCII: set[str] = {
    # The fix script's mapping table literally MUST contain the
    # non-ASCII chars it's replacing -- that's the source side of
    # the substitution. The file is run once by hand to normalize
    # legacy mojibake; it's not loaded by any module path.
    "scripts/fix_encoding.py",
}
# If you genuinely need a non-ASCII char (e.g. UTF-8 round-trip test),
# add the file's repo-relative path above with a comment explaining WHY.


def _candidates() -> list[Path]:
    exts = ("py", "md", "json", "txt", "sh")
    out: list[Path] = []
    for ext in exts:
        out.extend(ROOT.rglob(f"*.{ext}"))
    EXCLUDE_DIRS = {"__pycache__", ".git", ".venv", "venv",
                    "node_modules", "dist", "build", ".pytest_cache",
                    ".mypy_cache", ".ruff_cache"}
    return sorted(
        p for p in out
        if p.is_file()
        and not any(part in EXCLUDE_DIRS for part in p.parts)
    )


def main() -> int:
    failures: list[tuple[Path, int, str]] = []
    for fp in _candidates():
        rel = fp.relative_to(ROOT).as_posix()
        if rel in ALLOW_NON_ASCII:
            continue
        try:
            text = fp.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append((fp, -1, "not valid UTF-8"))
            continue
        for i, ch in enumerate(text):
            if ord(ch) > 127:
                # Find the line number for a useful error
                line_no = text.count("\n", 0, i) + 1
                failures.append((
                    fp, line_no,
                    f"U+{ord(ch):04X} at line {line_no} "
                    f"(byte offset {i})",
                ))
                break  # one report per file is plenty
    if failures:
        for fp, _line, msg in failures:
            sys.stdout.write(f"  FAIL: {fp.relative_to(ROOT)}: {msg}\n")
        sys.stdout.write(
            f"\n{len(failures)} file(s) contain non-ASCII characters. "
            "Run `py -3.13 scripts/fix_encoding.py` to normalize.\n"
        )
        return 1
    print("[PASS] every tracked file is pure ASCII")
    return 0


if __name__ == "__main__":
    sys.exit(main())
