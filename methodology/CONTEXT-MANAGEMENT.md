# Context management

Claude Code's context window is 200k tokens. Performance degrades as
it fills. **Most Claude Code failure modes are context-management
failures.** The persona-mvp-kit's discipline reduces them -- but you
still need the explicit toolkit.

## What survives a session, what doesn't

| Thing | Survives session? | Survives auto-compaction? |
|---|---|---|
| `CLAUDE.md` | Yes (reloaded every session) | Yes (re-injected after compact) |
| `personas.md` / `mvp-spec.md` | Read when referenced | Yes (referenced in CLAUDE.md) |
| `gap-log.md` | Read when referenced | Re-read on demand |
| Skills (description only) | Yes (~100 tokens each) | Yes |
| Skills (body, when invoked) | Yes (counted to 5k each) | First 5k of each, capped at 25k combined |
| Subagent results | Summary only | Summary only |
| File contents you Read | Yes | Mostly summarized away |
| Tool call outputs | Yes | Mostly summarized away |
| Conversation messages | Yes | Compressed/summarized when context fills |

## The four context controls

### `/clear`
Resets the conversation entirely. Use between unrelated tasks.

> When to use: switching from "implementing feature A" to "debugging
> issue B." Long sessions with mixed contexts hurt performance.

### `/compact <instructions>`
Manually trigger compaction. Optional instructions guide what to
preserve.

> Example: `/compact Focus on the brief module changes and the
> failing tests. Drop unrelated file reads.`

### `/rewind` (or `Esc Esc`)
Open the checkpoint menu. Restore conversation only, code only, or
both. Or summarize from a selected message.

> When to use: you made a wrong turn 30 messages ago. Don't keep
> correcting; rewind to the checkpoint before the wrong turn.

### `/btw`
Side-question that doesn't enter conversation history. Useful for
"what does this flag do" without growing context.

## Auto-compaction

When context fills (~80% of 200k), Claude Code automatically:

1. Summarizes the conversation into key facts/decisions
2. Re-injects `CLAUDE.md`
3. Re-attaches the most recent invocation of each skill (first 5k
   tokens, combined budget 25k)
4. Continues from the summary

What's preserved across compaction:
- All persona-mvp-kit project files (`CLAUDE.md`, `personas.md`,
  `mvp-spec.md`, `gap-log.md`) via `@path` references
- The latest invocation of each skill
- Recent file edits

What's lost:
- Most conversation history (replaced by summary)
- File contents read but not recently referenced
- Subagent results beyond their summary

The kit's `SessionStart` hook on `compact` matcher re-injects the
critical message: "Read CLAUDE.md, personas.md, mvp-spec.md,
gap-log.md before proceeding." This counters compaction drift.

## Strategies for context discipline

### Use subagents for heavy reads
A subagent has its own 200k window. Delegate "read 50 files and find
all callers of `foo`" to a subagent; it returns the summary, your
main context stays clean.

The kit defines three subagents (`persona-validator`,
`brutal-reviewer`, `root-cause-tracer`) precisely so the heavy work
happens elsewhere.

### Scope file reads narrowly
Don't `Read` a 5000-line file when you only need the function on
lines 400-450. Use `Read` with `offset` and `limit`. Use Grep to find
what you need before Reading.

### Prefer Glob/Grep over Read for discovery
"Where is X defined?" -> Grep, not Read every file.
"What files match pattern?" -> Glob, not ls/find.

### Use `@path` imports in CLAUDE.md
Long instructions reference shorter files. `@methodology/01-PERSONAS.md`
in CLAUDE.md keeps the master file lean while making the detailed doc
available on demand.

### Set MAX_TOKENS / WITHIN_LATENCY_MS in queries
For LLM-using systems, cap retrieval payloads. Reduces token cost,
forces better ranking.

### `/clear` between unrelated tasks
Don't accumulate context across tasks. A fresh session with a
better-written prompt outperforms a long session with accumulated
corrections.

## The status line

Install a custom status line (`/statusline`) to track context fill
in real time. When you see context at 60%+, decide actively:

- Am I still on the same task? -> keep going
- Switching tasks? -> `/clear`
- Mid-task but loaded a lot of irrelevant content? -> `/compact <focus>`

## Anti-patterns

### "Let me read the whole codebase first"
Reads hundreds of files into your context. Use the `Explore`
subagent instead.

### Correcting more than twice on the same issue
Context is now polluted with failed approaches. `/clear` and start
with a better prompt that incorporates what you learned.

### Long sessions with many unrelated micro-tasks
The "kitchen sink session." Each unrelated task adds noise that
hurts later tasks. Better: short focused sessions, `/clear` between.

### Skipping `/clear` because you "might need" past context
You usually don't. The summary preserves what matters. If you DO
need context, `/rewind` to a checkpoint instead of carrying
everything forward.

### Long CLAUDE.md files
The kit's master CLAUDE.md is ~110 lines. Per official guidance:
"If CLAUDE.md is too long, Claude ignores half of it because
important rules get lost in the noise. Ruthlessly prune."

## When to escalate to a new session

Start a fresh session when:

- The current task is done and the next is unrelated
- Two+ corrections on the same issue (`/clear` and prompt better)
- Context has accumulated 60%+ of file reads you don't need
- Switching from "exploration" to "implementation" (per the
  4-phase recipe: explore -> plan -> implement -> commit)

Resume a session (with `claude --resume` or `--continue`) when:

- You need to pick up where you left off
- The accumulated context is what makes the next step possible
- You named the session and want to come back to it

Per official guidance, name long-running sessions with `/rename`
("oauth-migration", "v0.2-maya-persona") so you can find them.

## Reference

- [Claude Code best practices Sec. Manage your session](https://code.claude.com/docs/en/best-practices)
- [How Claude Code works (agentic loop, context management)](https://code.claude.com/docs/en/how-claude-code-works)
- `@methodology/04-RUN-THE-WORKFLOW.md` -- when to use a fresh session
  for verification
- `.claude/agents/` -- the three subagents that keep main context clean
