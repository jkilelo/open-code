"""Layered settings + permission rules for open-code.

Three layers, lowest precedence first:
  1. ~/.open-code/settings.json         (user)
  2. <cwd>/.open-code/settings.json     (project, committed)
  3. <cwd>/.open-code/settings.local.json (gitignored, per-machine)

CLI flags + env vars override merged settings (handled in cli.py).

Schema (Claude Code-compatible subset):
{
  "model": "gemini-3.1-flash-lite-preview",
  "max_iterations": 25,
  "permissions": {
    "allow": ["read_file(*)", "list_dir(*)"],
    "ask":   ["write_file(*)"],
    "deny":  ["run_shell(rm -rf *)", "run_shell(sudo *)"]
  },
  "hooks":     { "disabled": false },
  "statusLine":{ "template": "...", "enabled": true }
}

Matcher syntax for permission rules:
  Tool             matches any args
  Tool(specifier)  fnmatch on the args' string form or any string arg
  Tool(/regex/)    regex search over the args' string form

Evaluation order: deny > ask > allow > default (allow).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


USER_SETTINGS_PATH = Path.home() / ".open-code" / "settings.json"
PROJECT_SETTINGS_REL = ".open-code/settings.json"
PROJECT_LOCAL_SETTINGS_REL = ".open-code/settings.local.json"


@dataclass
class PermissionRules:
    allow: list[str] = field(default_factory=list)
    ask: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    # Tier 2 #17 — sticky session permissions. Written by the REPL's
    # "always" prompt choice. Wins over ask rules but loses to deny,
    # so the user can override a project-level ask=tool rule by
    # adding tool to their .open-code/settings.local.json
    # `permissions.always_allow` list.
    always_allow: list[str] = field(default_factory=list)


VALID_MODES = ("default", "acceptEdits", "plan", "auto", "bypassPermissions")
VALID_EFFORTS = ("low", "medium", "high", "xhigh")


@dataclass
class Settings:
    """The merged settings handed to run_loop."""
    model: str | None = None
    max_iterations: int | None = None
    permissions: PermissionRules = field(default_factory=PermissionRules)
    hooks_disabled: bool = False
    statusline_template: str | None = None
    mode: str = "default"  # one of VALID_MODES
    # Architect/editor model split (Aider-style). When set, /plan uses
    # `architect_model` and /act uses `editor_model`. Falls back to
    # `model` (or the REPL's current_model) when None.
    architect_model: str | None = None
    editor_model: str | None = None
    # Effort level (Claude Code-style). Maps to a thinking_budget in
    # the Gemini config. "medium" is the default; "low"=0 thinking,
    # "high"=4096, "xhigh"=16384.
    effort: str = "medium"
    # Shadow-git checkpoints (Tier 2 #11). When True, run_loop snapshots
    # the working tree into `.open-code/checkpoints.git/` at the start
    # of each turn. Off by default — requires `git` binary on PATH.
    auto_checkpoint: bool = False
    raw: dict[str, Any] = field(default_factory=dict)
    # Per-file paths that contributed (for diagnostics)
    sources: list[Path] = field(default_factory=list)


def _load_one(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge overlay into base. Lists in permissions union; otherwise replace."""
    out: dict[str, Any] = dict(base)
    for k, v in overlay.items():
        if (k == "permissions" and isinstance(v, dict)
                and isinstance(out.get("permissions"), dict)):
            merged = dict(out["permissions"])
            for pk, pv in v.items():
                if pk in ("allow", "ask", "deny", "always_allow") and isinstance(pv, list):
                    existing = merged.get(pk, [])
                    if not isinstance(existing, list):
                        existing = []
                    seen = {x for x in existing if isinstance(x, str)}
                    merged[pk] = [x for x in existing] + [
                        x for x in pv if isinstance(x, str) and x not in seen
                    ]
                else:
                    merged[pk] = pv
            out["permissions"] = merged
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_layered_settings(cwd: Path) -> Settings:
    """Read user / project / local in order; deep-merge; return Settings."""
    user_path = USER_SETTINGS_PATH
    project_path = cwd / PROJECT_SETTINGS_REL
    local_path = cwd / PROJECT_LOCAL_SETTINGS_REL

    user = _load_one(user_path) or {}
    project = _load_one(project_path) or {}
    local = _load_one(local_path) or {}

    merged = _merge(_merge(user, project), local)

    perm_dict = merged.get("permissions") or {}
    perm = PermissionRules(
        allow=[r for r in (perm_dict.get("allow") or []) if isinstance(r, str)],
        ask=[r for r in (perm_dict.get("ask") or []) if isinstance(r, str)],
        deny=[r for r in (perm_dict.get("deny") or []) if isinstance(r, str)],
        always_allow=[r for r in (perm_dict.get("always_allow") or [])
                      if isinstance(r, str)],
    )
    hooks_disabled = bool((merged.get("hooks") or {}).get("disabled", False))
    sl = merged.get("statusLine") or {}
    statusline_template = sl.get("template") if isinstance(sl, dict) else None

    sources: list[Path] = []
    for p, raw in ((user_path, user), (project_path, project), (local_path, local)):
        if raw:
            sources.append(p)

    mode_raw = merged.get("mode")
    mode = mode_raw if isinstance(mode_raw, str) and mode_raw in VALID_MODES else "default"

    models_dict = merged.get("models") or {}
    architect_model = (models_dict.get("architect")
                       if isinstance(models_dict, dict) else None)
    editor_model = (models_dict.get("editor")
                    if isinstance(models_dict, dict) else None)
    if not isinstance(architect_model, str):
        architect_model = None
    if not isinstance(editor_model, str):
        editor_model = None

    effort_raw = merged.get("effort")
    effort = effort_raw if isinstance(effort_raw, str) and effort_raw in VALID_EFFORTS else "medium"

    cps = merged.get("checkpoints") or {}
    auto_checkpoint = bool(cps.get("auto", False)) if isinstance(cps, dict) else False

    return Settings(
        model=merged.get("model") if isinstance(merged.get("model"), str) else None,
        max_iterations=(merged.get("max_iterations")
                        if isinstance(merged.get("max_iterations"), int) else None),
        permissions=perm,
        hooks_disabled=hooks_disabled,
        statusline_template=statusline_template,
        mode=mode,
        architect_model=architect_model,
        editor_model=editor_model,
        effort=effort,
        auto_checkpoint=auto_checkpoint,
        raw=merged,
        sources=sources,
    )


_RULE_RE = re.compile(r"^\s*(\w+)(?:\((.+)\))?\s*$")


def _match_rule(rule: str, tool: str, args: dict[str, Any]) -> bool:
    """Does `rule` (e.g. 'run_shell(rm *)') match this tool call?"""
    m = _RULE_RE.match(rule)
    if not m:
        return False
    rule_tool = m.group(1)
    spec = m.group(2)
    if rule_tool != tool:
        return False
    if spec is None:
        return True
    args_str = json.dumps(args, sort_keys=True) if args else ""
    # Regex form: /pattern/
    if len(spec) >= 2 and spec.startswith("/") and spec.endswith("/"):
        try:
            return bool(re.search(spec[1:-1], args_str))
        except re.error:
            return False
    # fnmatch over the JSON-serialized args OR any string arg value
    if fnmatch(args_str, spec):
        return True
    for v in args.values():
        if isinstance(v, str) and fnmatch(v, spec):
            return True
    return False


def evaluate_permission(
    tool: str, args: dict[str, Any], perm: PermissionRules
) -> tuple[str, str]:
    """Return (decision, reason). decision ∈ {"allow","ask","deny"}.

    Evaluation order: deny > ask > allow. Default if no rules match
    is allow.
    """
    for rule in perm.deny:
        if _match_rule(rule, tool, args):
            return ("deny", f"matched deny rule {rule!r}")
    # always_allow beats ask (Tier 2 #17). Lets a project-local
    # "always" decision override a higher-layer ask rule.
    for rule in perm.always_allow:
        if _match_rule(rule, tool, args):
            return ("allow", f"matched always_allow rule {rule!r}")
    for rule in perm.ask:
        if _match_rule(rule, tool, args):
            return ("ask", f"matched ask rule {rule!r}")
    for rule in perm.allow:
        if _match_rule(rule, tool, args):
            return ("allow", f"matched allow rule {rule!r}")
    return ("allow", "default allow (no rules matched)")
