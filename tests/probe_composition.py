"""Composition: in ONE session, exercise:
- settings.json with permission rules + mode
- hooks (PreToolUse blocking)
- skill expansion
- apply_patch wiring
- subagents discovery

We're not running the model -- we exercise the SUPPORTING infrastructure
in the same temp project to verify all five feature modules cooperate
without surprising interaction.
"""
from __future__ import annotations
import sys, pathlib, tempfile, os, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

td = pathlib.Path(tempfile.mkdtemp(prefix="oc-composition-"))
print(f"temp project: {td}")

# 1. settings.json
(td / ".open-code").mkdir()
(td / ".open-code" / "settings.json").write_text(json.dumps({
    "model": "gemini-3.1-flash-lite-preview",
    "permissions": {
        "deny":  ["run_shell(curl *)"],
        "ask":   ["write_file(*)"],
        "allow": ["read_file(*)", "list_dir(*)"],
    },
    "hooks": {"disabled": False},
    "mode": "default",
    "models": {"architect": "gemini-3.1-pro-preview",
               "editor": "gemini-3.1-flash-lite-preview"},
    "mcpServers": {},
}), encoding="utf-8")

# 2. hooks
(td / ".open-code" / "hooks").mkdir()
(td / ".open-code" / "hooks" / "PreToolUse").mkdir()
pre = (td / ".open-code" / "hooks" / "PreToolUse" / "00-block-rm.py")
pre.write_text(
    "import sys, json\n"
    "d = json.loads(sys.stdin.read())\n"
    "cmd = (d.get('args') or {}).get('command', '')\n"
    "if d.get('tool') == 'run_shell' and 'rm ' in cmd:\n"
    "    sys.stderr.write('blocked by project policy')\n"
    "    sys.exit(2)\n"
    "sys.exit(0)\n",
    encoding="utf-8",
)
if os.name != "nt":
    pre.chmod(0o755)

# 3. skill
(td / ".open-code" / "skills").mkdir()
(td / ".open-code" / "skills" / "review-pr").mkdir()
(td / ".open-code" / "skills" / "review-pr" / "SKILL.md").write_text(
    "---\nname: review-pr\ndescription: do a brutal PR review\nallowed-tools: read_file, list_dir\n---\n"
    "Review PR $1. Project state:\n!`echo summary`\n\nGo deep.\n",
    encoding="utf-8",
)

# 4. agent
(td / ".open-code" / "agents").mkdir()
(td / ".open-code" / "agents" / "explorer.md").write_text(
    "---\nname: explorer\ndescription: read-only investigator\nallowed-tools: read_file, list_dir\n---\n"
    "You are an exploration subagent. Look around and summarize.\n",
    encoding="utf-8",
)

# Now: verify each subsystem loads from THIS project, and they don't
# interfere.
import settings as _settings
S = _settings.load_layered_settings(td)
print(f"\n[settings] mode={S.mode}  hooks_disabled={S.hooks_disabled}")
print(f"[settings] deny rules={S.permissions.deny}")
print(f"[settings] arch={S.architect_model}  editor={S.editor_model}")
assert S.mode == "default"
assert "run_shell(curl *)" in S.permissions.deny
assert S.architect_model == "gemini-3.1-pro-preview"

import hooks as _hooks
# v0.14.2: explicit trust required before any hook will fire.
_hooks.mark_project_trusted(td, "allow", persist=False)
r = _hooks.fire("PreToolUse", td, session_id="sess1",
                payload={"tool": "run_shell", "args": {"command": "rm hello.py"}})
print(f"[hooks] PreToolUse for rm: blocked={r.block} reason={r.reason!r}")
assert r.block

r2 = _hooks.fire("PreToolUse", td, session_id="sess1",
                 payload={"tool": "run_shell", "args": {"command": "echo hi"}})
print(f"[hooks] PreToolUse for echo: blocked={r2.block}")
assert not r2.block

import skills as _skills
sks = _skills.discover_skills(td)
print(f"\n[skills] found {len(sks)}: {[s.name for s in sks]}")
expanded = _skills.expand_skill_body(sks[0], "42", td)
print(f"[skills] expanded body: {expanded!r}")
assert "Review PR 42" in expanded
assert "summary" in expanded
assert "!`echo summary`" not in expanded  # command block resolved

import subagents as _subagents
ags = _subagents.discover_agents(td)
print(f"\n[agents] found {len(ags)}: {[a.name for a in ags]}")
assert ags[0].allowed_tools == ["read_file", "list_dir"]

# Permission evaluation: run_shell(curl ...) should DENY
import settings as _s2
d, why = _s2.evaluate_permission("run_shell", {"command": "curl https://x"},
                                  S.permissions)
print(f"\n[perm] curl call -> ({d}, {why!r})")
assert d == "deny"

d, why = _s2.evaluate_permission("write_file", {"path": "foo.py", "content": ""},
                                  S.permissions)
print(f"[perm] write call -> ({d}, {why!r})")
assert d == "ask"

# apply_patch
import tools, patches
tools.CONFIG.cwd = td
target = td / "hello.py"
target.write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
patch = """\
*** Begin Patch
*** Update File: hello.py
@@ def greet
-    return 'hi'
+    return 'hello world'
*** End Patch
"""
res = patches.apply_patch(patch)
print(f"\n[patches] apply_patch result: ok={res['ok']} applied={res.get('applied')}")
print(f"[patches] file after: {target.read_text()!r}")

print("\n[OK] composition wiring works: settings + hooks + skills + agents + patches all load and interoperate.")
