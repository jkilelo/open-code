---
description: Extract personas from the user's request before any code is written.
---

You are starting a new build session under the persona-mvp-kit standard.

If `personas.md` already exists at the project root, READ IT and ask the user
to confirm it still applies. Don't re-extract from scratch.

If `personas.md` does NOT exist:

1. Read the user's most recent prompt or this session's stated goal.

2. Identify which of these are present and which are missing:
   - **Who** specifically uses this (job title + organization type)
   - **What workflow** they care most about
   - **What they do today** instead (current pain)
   - **What success looks like** concretely

3. Ask UP TO 4 questions to fill missing items. Don't ask things you
   can already infer.

4. Once you have the four pieces, draft `personas.md` from
   `templates/persona.md`. Include 1 primary persona; add 1-2
   secondary personas only if the user mentioned multiple use cases.

5. Show the file to the user. Ask:
   "Does this match what you have in mind? Refine or confirm before
   I move to MVP spec."

Do NOT write any code. Do NOT scaffold any directories. Do NOT install
any dependencies. The output of this command is `personas.md` only.

Reference: `methodology/01-PERSONAS.md`.
