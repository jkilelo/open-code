"""One-shot script: normalize every file to pure ASCII.

Two passes:
  1. Replace known mojibake (UTF-8 misread as cp1252 then re-encoded)
     sequences with their original ASCII intent.
  2. Replace remaining non-ASCII characters with ASCII equivalents.

The user's requirement is "100% no encoding issues in any platform,"
so this script enforces pure ASCII across .py / .md / .json / .txt /
.sh files. The script itself stays pure ASCII -- every non-ASCII
codepoint is expressed via Python \\u escapes, never as literal chars,
so the source file's bytes are 7-bit clean.

Idempotent: running again does nothing.
"""
from __future__ import annotations
import sys
from pathlib import Path


# Mojibake sequences -> intended ASCII replacement.
# Each key is the cp1252-misread of a UTF-8 byte sequence:
#   em-dash      U+2014  E2 80 94  -> cp1252: "â€”"
#   ellipsis     U+2026  E2 80 A6  -> cp1252: "â€¦"
#   right-arrow  U+2192  E2 86 92  -> cp1252: "â†’"
#   right-pntr   U+25B6  E2 96 B6  -> cp1252: "â–¶"
#   check        U+2713  E2 9C 93  -> cp1252: "âœ“"
#   ballot-X     U+2717  E2 9C 97  -> cp1252: "âœ—"
MOJIBAKE: dict[str, str] = {
    "â€”": "--",     # em-dash mojibake
    "â€¦": "...",    # ellipsis mojibake
    "â†’": "->",     # right-arrow mojibake
    "â–¶": ">",      # right-pointer mojibake
    "âœ“": "[OK]",   # check-mark mojibake
    "âœ—": "[X]",    # ballot-X mojibake
}

# Single-char non-ASCII -> ASCII. Every key uses \u or \U escapes.
CHAR_MAP: dict[str, str] = {
    # Punctuation & dashes
    "—": "--",     # em dash
    "–": "-",      # en dash
    "…": "...",    # ellipsis
    "‘": "'",      # left single quote
    "’": "'",      # right single quote
    "“": '"',      # left double quote
    "”": '"',      # right double quote
    "·": ".",      # middle dot
    "§": "Sec.",   # section sign
    "¶": "P.",     # pilcrow
    "²": "^2",     # superscript 2
    "³": "^3",     # superscript 3
    "×": "x",      # multiplication sign
    "÷": "/",      # division sign
    "¦": "|",      # broken bar
    # Arrows
    "→": "->",     # right arrow
    "←": "<-",     # left arrow
    "↑": "^",      # up arrow
    "↓": "v",      # down arrow
    "⇒": "=>",     # double right arrow
    "⇐": "<=",     # double left arrow
    "↻": "(loop)", # clockwise open circle arrow
    # Math
    "≤": "<=",     # less-or-equal
    "≥": ">=",     # greater-or-equal
    "≠": "!=",     # not-equal
    "≈": "~",      # approximately
    "∈": "in",     # element of
    "°": "deg",    # degree sign
    # Box / marker
    "▶": ">",      # black right-pointing triangle
    "◀": "<",      # black left-pointing triangle
    "✓": "[OK]",   # check
    "✗": "[X]",    # ballot X
    "✅": "[OK]",   # white heavy check
    "❌": "[FAIL]", # cross mark
    # Status emoji (>U+FFFF -> 8-digit \U escapes)
    "\U0001f7e2": "[OK]",     # green circle
    "\U0001f7e1": "[WARN]",   # yellow circle
    "\U0001f534": "[FAIL]",   # red circle
    "⚪": "[ ]",          # white medium circle
    "⚫": "[X]",          # black medium circle
    "\U0001f389": "(done)",   # party popper
    "\U0001f916": "(bot)",    # robot
    "\U0001f6e1": "(guard)",  # shield
    "\U0001f527": "(fix)",    # wrench
    # Common latin accented (defensive)
    "à": "a", "á": "a", "â": "a",
    "è": "e", "é": "e", "ê": "e",
    "ï": "i", "ñ": "n", "ö": "o",
    "ü": "u",
    # Mojibake leftovers (defensive after MOJIBAKE pass)
    "€": "",       # euro
    "œ": "",       # oe ligature
    "†": "",       # dagger
}


def normalize(text: str) -> str:
    for src, dst in MOJIBAKE.items():
        text = text.replace(src, dst)
    for src, dst in CHAR_MAP.items():
        text = text.replace(src, dst)
    return text


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    targets: list[Path] = []
    for ext in ("py", "md", "json", "txt", "sh"):
        targets.extend(root.rglob(f"*.{ext}"))
    EXCLUDE_DIRS = {"__pycache__", ".git", ".venv", "venv",
                    "node_modules", "dist", "build"}
    targets = [p for p in targets
               if not any(part in EXCLUDE_DIRS for part in p.parts)]
    targets = [p for p in targets if p.is_file()]
    self_path = Path(__file__).resolve()
    targets = [p for p in targets if p.resolve() != self_path]

    changed = 0
    for fp in sorted(targets):
        try:
            text = fp.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new = normalize(text)
        if new != text:
            fp.write_text(new, encoding="utf-8", newline="\n")
            changed += 1
            sys.stdout.write(f"  fixed: {fp.relative_to(root)}\n")
    sys.stdout.write(f"\nFiles changed: {changed}\n")

    leftovers = 0
    for fp in sorted(targets):
        try:
            text = fp.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        bad = [(i, ch) for i, ch in enumerate(text) if ord(ch) > 127]
        if bad:
            leftovers += 1
            sample = ", ".join(f"U+{ord(ch):04X}" for _, ch in bad[:3])
            sys.stdout.write(
                f"  LEFTOVER: {fp.relative_to(root)} "
                f"({len(bad)} chars; first: {sample})\n"
            )
    if leftovers:
        sys.stdout.write(f"\n{leftovers} files still contain non-ASCII.\n")
        return 1
    sys.stdout.write("\nVerified: 100% ASCII across all targeted files.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
