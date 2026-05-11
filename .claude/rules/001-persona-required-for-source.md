---
paths:
  - "src/**/*"
  - "lib/**/*"
  - "app/**/*"
  - "**/*.{py,ts,tsx,js,jsx,rs,go,java,rb,c,cpp,h,sql}"
---

# Persona-required rule (source files)

You are editing a source file. The persona-mvp-kit standard requires
`personas.md` and `mvp-spec.md` to exist + be user-confirmed before
ANY source-file edit.

If you got here via the `PreToolUse` hook, the hook already verified
this — you may proceed.

If the hook is disabled or you're operating outside the hook
(`--permission-mode bypassPermissions`), STOP NOW and verify
yourself:

```bash
test -s personas.md || echo "MISSING — run /persona-extract"
test -s mvp-spec.md || echo "MISSING — run /mvp-spec"
```

Bright line #4: never claim done without running the workflow as
the persona. Bright line #6: never add features beyond the spec
without re-confirming personas. See `@CLAUDE.md`.

## What "source file" means

This rule loads when you edit any of:
- `src/**`, `lib/**`, `app/**` directories
- Files with extensions `.py .ts .tsx .js .jsx .rs .go .java .rb .c .cpp .h .sql`

Documentation, config, and kit-internal files don't load this rule —
they're allowed before personas exist (so the kit can write
`personas.md` itself).
