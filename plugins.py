"""Plugins system (Tier 2 #22) -- bundles of skills + agents + styles.

A plugin is a directory at one of:

    <cwd>/.open-code/plugins/<plugin-name>/   (project-installed)
    ~/.open-code/plugins/<plugin-name>/       (user-installed)

Each plugin has a `plugin.json` manifest:

    {
      "name": "my-plugin",
      "version": "1.0.0",
      "description": "...",
      "homepage": "https://...",     (optional)
      "exposes": {
        "skills":        ["review-pr", "format-changelog"],
        "agents":        ["counter"],
        "output_styles": ["zen-mode"]
      }
    }

Directory layout (asset paths are RELATIVE to the plugin root):

    .open-code/plugins/my-plugin/
        plugin.json
        skills/review-pr/SKILL.md
        skills/format-changelog/SKILL.md
        agents/counter.md
        output-styles/zen-mode.md

v0.23.0 ships:
- Plugin discovery from project + user dirs
- Aggregation of plugin-provided skills, agents, output styles into
  the existing discovery functions
- `--list-plugins` CLI flag

v0.23.0 deliberately DOES NOT ship:
- Plugin-provided hooks (security: would need its own trust prompt)
- A marketplace / registry (out of scope)
- Plugin install/uninstall commands (just `git clone` or
  `mkdir + cp` for now)

Trust model: a plugin under `<cwd>/.open-code/plugins/` is treated
as project-trusted (same as the project's own skills/agents). A
plugin under `~/.open-code/plugins/` is user-trusted (you put it
there). We do NOT add a separate trust prompt for plugins because
they expose only declarative prompt content, not executable hooks.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


USER_PLUGINS_DIR = Path.home() / ".open-code" / "plugins"
PROJECT_PLUGINS_REL = ".open-code/plugins"


@dataclass
class Plugin:
    """A discovered plugin."""
    name: str
    version: str
    description: str
    path: Path  # root of the plugin dir
    source: str  # "project" or "user"
    exposes_skills: list[str] = field(default_factory=list)
    exposes_agents: list[str] = field(default_factory=list)
    exposes_output_styles: list[str] = field(default_factory=list)
    homepage: str = ""


def _load_plugin(plugin_dir: Path, source: str) -> Plugin | None:
    """Parse a plugin dir's plugin.json into a Plugin, or None if invalid."""
    manifest = plugin_dir / "plugin.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("name") or plugin_dir.name
    if not isinstance(name, str) or not name:
        return None
    exposes = data.get("exposes") or {}
    if not isinstance(exposes, dict):
        exposes = {}

    def _list_of_str(key: str) -> list[str]:
        v = exposes.get(key)
        if not isinstance(v, list):
            return []
        return [x for x in v if isinstance(x, str)]

    return Plugin(
        name=name,
        version=str(data.get("version") or "0.0.0"),
        description=str(data.get("description") or "").strip(),
        path=plugin_dir,
        source=source,
        exposes_skills=_list_of_str("skills"),
        exposes_agents=_list_of_str("agents"),
        exposes_output_styles=_list_of_str("output_styles"),
        homepage=str(data.get("homepage") or "").strip(),
    )


def discover_plugins(cwd: Path) -> list[Plugin]:
    """Find every installed plugin (project + user).

    If a plugin name appears in BOTH layers, the project plugin wins
    (caller sees it; the user copy is dropped). Same precedence pattern
    as output_styles / skills.
    """
    out: dict[str, Plugin] = {}
    if USER_PLUGINS_DIR.exists() and USER_PLUGINS_DIR.is_dir():
        for entry in sorted(USER_PLUGINS_DIR.iterdir()):
            if not entry.is_dir():
                continue
            p = _load_plugin(entry, "user")
            if p is not None:
                out[p.name] = p
    proj_root = cwd / PROJECT_PLUGINS_REL
    if proj_root.exists() and proj_root.is_dir():
        for entry in sorted(proj_root.iterdir()):
            if not entry.is_dir():
                continue
            p = _load_plugin(entry, "project")
            if p is not None:
                out[p.name] = p
    return sorted(out.values(), key=lambda p: p.name)


def list_plugin_skill_dirs(cwd: Path) -> list[tuple[Path, Plugin]]:
    """Return [(skill_dir_containing_SKILL_md, plugin)] for every plugin-exposed skill.

    skill_dir is the directory holding SKILL.md (per the existing skills.py
    contract). Used by skills.discover_skills to aggregate.
    """
    out: list[tuple[Path, Plugin]] = []
    for plugin in discover_plugins(cwd):
        for skill_name in plugin.exposes_skills:
            candidate = plugin.path / "skills" / skill_name / "SKILL.md"
            if candidate.is_file():
                out.append((candidate, plugin))
    return out


def list_plugin_agent_files(cwd: Path) -> list[tuple[Path, Plugin]]:
    """Return [(agent_md_path, plugin)] for every plugin-exposed agent."""
    out: list[tuple[Path, Plugin]] = []
    for plugin in discover_plugins(cwd):
        for agent_name in plugin.exposes_agents:
            # Two conventions: <agents>/<name>.md or <agents>/<name>/AGENT.md.
            simple = plugin.path / "agents" / f"{agent_name}.md"
            nested = plugin.path / "agents" / agent_name / "AGENT.md"
            if simple.is_file():
                out.append((simple, plugin))
            elif nested.is_file():
                out.append((nested, plugin))
    return out


def list_plugin_output_styles(cwd: Path) -> list[tuple[str, Path, Plugin]]:
    """Return [(style_name, style_md_path, plugin)] for every plugin-exposed style."""
    out: list[tuple[str, Path, Plugin]] = []
    for plugin in discover_plugins(cwd):
        for style_name in plugin.exposes_output_styles:
            candidate = plugin.path / "output-styles" / f"{style_name}.md"
            if candidate.is_file():
                out.append((style_name, candidate, plugin))
    return out


def render_plugin_listing(plugins: list[Plugin]) -> str:
    """Format plugins for `--list-plugins` output."""
    if not plugins:
        return "(no plugins installed)"
    lines = [
        f"{'NAME':<24}  {'VERSION':<10}  {'SOURCE':<8}  EXPOSES",
        "-" * 80,
    ]
    for p in plugins:
        exposed_bits: list[str] = []
        if p.exposes_skills:
            exposed_bits.append(f"skills={len(p.exposes_skills)}")
        if p.exposes_agents:
            exposed_bits.append(f"agents={len(p.exposes_agents)}")
        if p.exposes_output_styles:
            exposed_bits.append(f"styles={len(p.exposes_output_styles)}")
        exposed = ", ".join(exposed_bits) or "(nothing)"
        lines.append(
            f"{p.name:<24}  {p.version:<10}  {p.source:<8}  {exposed}"
        )
        if p.description:
            lines.append(f"  {p.description}")
    return "\n".join(lines)
