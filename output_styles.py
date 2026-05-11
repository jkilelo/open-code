"""Output styles (Tier 2 #23) — system_instruction overlays.

Modeled on Claude Code's named output styles. A style is a short
block of guidance appended to the system_instruction that shifts
the model's TONE — concise/verbose/explanatory/etc. — without
changing capabilities.

Built-in styles ship as Python strings. Users can also drop
markdown files at `.open-code/output-styles/<name>.md` (or the
ancestor walk, or `~/.open-code/output-styles/<name>.md`); the
file body becomes the overlay verbatim.

Resolution order:
  1. Custom style at `<cwd>/.open-code/output-styles/<name>.md`
  2. Custom style at `~/.open-code/output-styles/<name>.md`
  3. Built-in style with the given name
  4. Built-in `default` (empty overlay) if nothing matches

The "default" style intentionally has an empty overlay — picking it
means "no styling beyond the base system_instruction."
"""
from __future__ import annotations

from pathlib import Path


# Built-in output styles. Keep these tight: the system instruction
# is already long; overlays add a few sentences each.
BUILTIN_STYLES: dict[str, str] = {
    "default": "",
    "concise": (
        "Keep responses brief. Lead with the answer. Skip context that "
        "the user already has. No filler phrases. Bullet points over "
        "prose when listing more than two items."
    ),
    "explanatory": (
        "Explain your reasoning at each step. Before calling a tool, "
        "state in one short sentence why. After receiving a tool result, "
        "summarize what it told you in one short sentence. The user is "
        "learning; transparency matters more than brevity."
    ),
    "learning": (
        "Treat the user as a learner. After each tool call, briefly "
        "describe what you learned and why it changes (or confirms) "
        "your plan. If you find an unfamiliar pattern in the code, "
        "name it. Prefer small steps with explanations over big leaps."
    ),
    "pair-programmer": (
        "You are pair-programming with the user. Before making changes "
        "larger than one file or one function, propose the change in "
        "one or two sentences and wait for confirmation. After each "
        "change, state what you'd verify next and let the user decide."
    ),
    "yolo": (
        "The user is in a hurry. Make decisions; don't ask. Bundle "
        "related changes. Skip preamble. Default to action; explain "
        "only on failure."
    ),
}


USER_STYLES_DIR = Path.home() / ".open-code" / "output-styles"
PROJECT_STYLES_REL = ".open-code/output-styles"


def list_available(cwd: Path) -> list[tuple[str, str]]:
    """Return (name, source) pairs for every discoverable style.

    `source` is "builtin", "user", or "project" so callers can show
    where each style came from.
    """
    seen: dict[str, str] = {}
    # Builtins win the name *unless* a more-specific location overrides.
    for name in BUILTIN_STYLES:
        seen[name] = "builtin"
    if USER_STYLES_DIR.exists():
        for f in USER_STYLES_DIR.glob("*.md"):
            seen[f.stem] = "user"
    proj_dir = cwd / PROJECT_STYLES_REL
    if proj_dir.exists():
        for f in proj_dir.glob("*.md"):
            seen[f.stem] = "project"
    return sorted(seen.items(), key=lambda kv: (kv[1] != "project", kv[0]))


def resolve_overlay(style_name: str, cwd: Path) -> tuple[str, str]:
    """Resolve a style name to (overlay_text, source_label).

    Resolution order: project file → user file → built-in → empty.
    Returns ("", "default") for the bare "default" style.
    """
    name = (style_name or "default").strip()
    if not name:
        return ("", "default")
    # Project-local first
    proj_file = cwd / PROJECT_STYLES_REL / f"{name}.md"
    if proj_file.is_file():
        try:
            return (proj_file.read_text(encoding="utf-8").strip(),
                    f"project:{proj_file}")
        except OSError:
            pass
    # User-level
    user_file = USER_STYLES_DIR / f"{name}.md"
    if user_file.is_file():
        try:
            return (user_file.read_text(encoding="utf-8").strip(),
                    f"user:{user_file}")
        except OSError:
            pass
    # Built-in
    if name in BUILTIN_STYLES:
        return (BUILTIN_STYLES[name], f"builtin:{name}")
    # Unknown name → no overlay (caller may want to warn)
    return ("", f"unknown:{name}")


def apply_to_system_instruction(base: str, style_name: str,
                                cwd: Path) -> tuple[str, str]:
    """Return (new_system_instruction, source_label).

    If the resolved overlay is empty, returns the base unchanged.
    """
    overlay, source = resolve_overlay(style_name, cwd)
    if not overlay:
        return (base, source)
    return (
        f"{base}\n\n## Output style: {style_name}\n\n{overlay}",
        source,
    )
