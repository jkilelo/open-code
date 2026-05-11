# Installing the kit into a new project

The kit is a directory tree. Copy it into your project's root,
preserving the structure.

## Prerequisites

| Tool | Required? | Used for | Install |
|---|---|---|---|
| `bash` | YES | All hook scripts | macOS/Linux/Git Bash/WSL bundled |
| `jq` | YES | 4 hooks parse stdin JSON | `brew install jq` / `apt install jq` / `scoop install jq` |
| `git` | YES | One-commit-per-gap discipline | system package manager |
| `find` (POSIX) | YES | Verification timestamp check | bundled |
| GNU coreutils | optional | Nicer date/time formatting | macOS: `brew install coreutils` |
| Claude Code v2.1.114+ | YES | `autoMode.allow/soft_deny` composition with `$defaults` | https://code.claude.com/docs/en/quickstart |
| Claude Code v2.1.128+ | recommended | `autoMode.hard_deny`, plugin from .zip URLs | as above |

The kit deliberately avoids Python/Node.js as hook dependencies.
Skill bodies may use them if your project needs them, but the
enforcement hooks are pure bash + jq.

After install, run the included `install-check.sh` to verify
everything's wired up:

```bash
bash .claude/hooks/install-check.sh
```

Expected output:
```
=== persona-mvp-kit install check ===
[1/5] External tools          [OK] bash / jq / git / find
[2/5] Kit structure           [OK] all dirs present
[3/5] Hook scripts executable [OK] all chmod +x
[4/5] JSON validity           [OK] settings/plugin/mcp valid
[5/5] Project state           ! personas.md absent (expected on first install)
[OK] Kit infrastructure is ready.
```

## What "install" means

After install, your project root has:

| Path | Effect |
|---|---|
| `CLAUDE.md` | Auto-loaded by Claude Code as the master rule file (~110 lines, imports from `methodology/`) |
| `.claude/settings.json` | Permissions + hooks (deterministic enforcement of the kit's bright lines) |
| `.claude/skills/` | Four skills auto-activated by Claude (or invoked via `/skill-name`) |
| `.claude/agents/` | Three subagents Claude delegates to for isolated work |
| `.claude/hooks/` | Shell scripts the hooks run (`require-personas.sh`, `remind-gap-log.sh`) |
| `.claude/commands/` | Slash commands (`/persona-extract`, `/mvp-spec`, `/run-as-persona`, `/trace-root-cause`) |
| `.mcp.json.example` | MCP server template -- rename to `.mcp.json` after editing |
| `methodology/` | 10 docs Claude reads on demand (via `@path` imports in CLAUDE.md) |
| `templates/` | Fill-in templates for `personas.md`, `mvp-spec.md`, `gap-log.md`, commit messages |
| `examples/` | Two worked examples Claude can reference |
| `prompts/starter-prompt.md` | Recommended initial prompt shapes |

The structure is what makes the kit work. Don't flatten or rename
folders without reading the relevant doc.

## Step-by-step

### Option A -- fresh project

```bash
mkdir my-new-app && cd my-new-app
git init

# Copy the kit (adjust source path to wherever you have the kit)
cp -r /path/to/persona-mvp-kit/. .

# Make the hook scripts executable (macOS/Linux/Git Bash)
chmod +x .claude/hooks/*.sh

# Optional: configure MCP servers
cp .mcp.json.example .mcp.json
# edit .mcp.json -- set GITHUB_TOKEN in your environment or remove the github block

# Verify the layout
ls -la
# Expected:
#  CLAUDE.md    .claude/    methodology/    skills/    templates/    examples/
#  README.md    INSTALL.md  prompts/       .mcp.json.example

# First commit
git add -A
git commit -m "Adopt persona-mvp-kit"
```

### Option B -- existing project

```bash
cd /path/to/existing-project

# Check for an existing CLAUDE.md
test -f CLAUDE.md && echo "WARNING: existing CLAUDE.md found -- decide: replace or merge"

# Copy non-overlapping pieces
cp -r /path/to/persona-mvp-kit/methodology .
cp -r /path/to/persona-mvp-kit/templates .
cp -r /path/to/persona-mvp-kit/examples .
cp -r /path/to/persona-mvp-kit/prompts .

# Merge the .claude/ tree carefully -- don't overwrite your own skills/commands/hooks
mkdir -p .claude/skills .claude/agents .claude/hooks .claude/commands
cp -r /path/to/persona-mvp-kit/.claude/skills/* .claude/skills/
cp -r /path/to/persona-mvp-kit/.claude/agents/* .claude/agents/
cp /path/to/persona-mvp-kit/.claude/hooks/*.sh .claude/hooks/
cp /path/to/persona-mvp-kit/.claude/commands/* .claude/commands/
chmod +x .claude/hooks/*.sh

# CAREFUL: settings.json may conflict with your existing config.
# Read both, merge by hand.
diff .claude/settings.json /path/to/persona-mvp-kit/.claude/settings.json

# CLAUDE.md: either replace or merge by hand
# The kit's CLAUDE.md is short (~110 lines) and uses @path imports --
# it can usually be appended to yours
cat /path/to/persona-mvp-kit/CLAUDE.md >> CLAUDE.md  # merge

# Or replace:
# cp /path/to/persona-mvp-kit/CLAUDE.md CLAUDE.md

git add -A
git commit -m "Adopt persona-mvp-kit"
```

### Option C -- install as a git submodule

If you maintain the kit as its own repo and want updates to flow:

```bash
git submodule add <kit-repo-url> persona-mvp-kit
# Symlink the auto-loaded files to project root
ln -s persona-mvp-kit/CLAUDE.md CLAUDE.md
ln -s persona-mvp-kit/.claude .claude
```

The submodule path stays out of your `src/` tree; the symlinks
make Claude Code pick up the kit.

## Interactive setup with `/init`

Claude Code's built-in `/init` command generates a starter CLAUDE.md
based on your codebase. If you already have CLAUDE.md from the kit,
`/init` will SUGGEST refinements rather than overwrite.

Set `CLAUDE_CODE_NEW_INIT=1` to enable the multi-phase flow that
asks which artifacts to set up (CLAUDE.md, skills, hooks), explores
your codebase, and presents a reviewable proposal before writing.

```bash
CLAUDE_CODE_NEW_INIT=1 claude
> /init
```

You can use `/init` after copying the kit to fill in project-specific
context the kit's generic CLAUDE.md doesn't know (build commands,
test runners, framework patterns).

## Useful built-in commands

The kit relies on these standard Claude Code commands:

- **`/init`** -- generate or refine CLAUDE.md
- **`/memory`** -- view/edit CLAUDE.md, CLAUDE.local.md, rules, auto-memory
- **`/skills`** -- browse skills (type-to-filter as of v2.1.120+)
- **`/agents`** -- manage subagents
- **`/hooks`** -- inspect hook configuration (read-only menu)
- **`/permissions`** -- review and adjust permission rules
- **`/config`** -- open the config UI (theme, editor mode, output style)
- **`/clear`** -- reset context between unrelated tasks
- **`/compact <focus>`** -- manually compact, optionally focused
- **`/rewind`** (or Esc Esc) -- restore to a previous checkpoint
- **`/recap`** -- generate a one-line recap of session activity
- **`/usage`** -- context/cost/stats (replaces /cost + /stats as of v2.1.114)
- **`/model`** -- switch model mid-session
- **`/permissions`** -- adjust permission allowlist
- **`/btw`** -- quick side question that doesn't enter context

## Verifying the install

After install, prompt Claude:

> Verify the persona-mvp-kit is installed correctly.

Claude should:

1. Read `CLAUDE.md` and confirm the 8 bright lines.
2. List the methodology files under `methodology/`.
3. List the four skills under `.claude/skills/`.
4. List the three subagents under `.claude/agents/`.
5. List the four slash commands under `.claude/commands/`.
6. Confirm `.claude/settings.json` is valid JSON and hook scripts
   are executable.
7. Check for `personas.md` and `mvp-spec.md`. If missing, prompt
   you to create them via `/persona-extract` before any code.

If Claude skips steps 1-6, the kit isn't being read. Common causes:

- Kit copied to a subdirectory instead of project root
- `CLAUDE.md` masked by an enterprise / parent `CLAUDE.md`
- Hook scripts not executable -- `chmod +x .claude/hooks/*.sh`
- `.claude/settings.json` has a JSON syntax error -- `cat .claude/settings.json | jq`

## What the hooks enforce

Once installed, the kit's `PreToolUse` hook on `Edit|Write` will
**block edits to source files when `personas.md` doesn't exist**.
Source files are `.py / .ts / .tsx / .js / .jsx / .rs / .go / .java
/ .rb / .c / .cpp / .h / .sql / Dockerfile`.

Doc/config files (`personas.md`, `mvp-spec.md`, `gap-log.md`,
`runs/*`, `.claude/*`, `CLAUDE.md`, `README.md`, `package.json`,
`pyproject.toml`, etc.) are NOT blocked -- so Claude can write
personas.md and the spec without fighting the hook.

To customize what's source vs doc, edit `.claude/hooks/require-personas.sh`.

## Updating the kit

Treat the kit as documentation, not code. When you have a hard-won
lesson from a real project, edit the relevant methodology file or
skill and commit. The next project you bootstrap inherits the
improvement.

If you maintain the kit centrally, propagate changes via:

- `git pull` in the submodule (Option C), or
- Re-copying (Options A/B)

Be careful with project-specific files -- `personas.md`, `mvp-spec.md`,
`gap-log.md`, `runs/*` should NOT be overwritten.

## Uninstalling

```bash
rm CLAUDE.md
rm -rf .claude methodology templates examples prompts
rm .mcp.json.example
rm INSTALL.md README.md
git add -A && git commit -m "Remove persona-mvp-kit"
```

Your `personas.md`, `mvp-spec.md`, `gap-log.md`, `runs/*` files are
project-specific -- they stay.

## Reference

- [Claude Code official docs](https://code.claude.com/docs/) -- for
  the underlying mechanics the kit builds on
- [Best practices](https://code.claude.com/docs/en/best-practices) --
  the kit aligns with all 5 sections
- [Skills](https://code.claude.com/docs/en/skills) -- frontmatter
  reference for adding your own
- [Hooks](https://code.claude.com/docs/en/hooks-guide) -- for
  customizing the enforcement layer
- [Subagents](https://code.claude.com/docs/en/sub-agents) -- for
  adding domain-specific specialists
