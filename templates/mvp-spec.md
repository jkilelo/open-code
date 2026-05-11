# MVP spec -- v0.1

> Fill out this file before writing any code. The four sections below
> are the entire spec. If you find yourself adding more sections,
> stop -- you're scope-creeping.

---

## Persona shipped

> Single name from `personas.md`. v0.1 serves THIS persona's primary
> workflow. Other personas wait for v0.2+.

**[Persona name]** -- see `personas.md` Sec. Primary.

---

## Success criterion (in their language, concretely)

> Quote the criterion verbatim from `personas.md`. Add measurable
> details: time bound, recall threshold, output format, failure mode
> they cannot tolerate.
>
> The criterion must pass the screenshot test: you should be able to
> imagine a screenshot or terminal output that obviously satisfies
> it. If you can't, it's too vague.
>
> Example:
>
> > "Sarah pastes 4 article URLs into a single web form, clicks
> > 'summarize.' Within 30s on warm cache (45s cold), the page shows
> > a 5-bullet brief, each bullet ending with `[^N]` citation linking
> > to the source URL. If sources disagree on a numerical claim, the
> > brief includes a `Contradictions:` section listing the
> > disagreements with fact_id refs. Sarah copies the markdown to
> > Slack."

---

## Smallest tech stack

> Each piece justified per-persona. See `skills/minimal-stack-selection/`
> for the default ladder.

- **[Technology X]** -- needed because [persona] needs [specific
  workflow detail]. Smallest viable choice for that need.
- **[Technology Y]** -- needed because [...]. Could alternatively use
  [smaller alternative]; chosen Y because [persona-relevant reason].
- ...

---

## OUT of v0.1

> Be explicit. Each item has a one-line reason. The list is a
> permission slip to say "no" later when scope creep arrives.

- **[Item 1]** -- [reason it's out, e.g. "persona is sole user"]
- **[Item 2]** -- [reason]
- **[Item 3]** -- [reason]

Common items that go OUT of v0.1:
- Authentication / authorization
- Database migrations
- Production deployment / Docker / CI
- Logging / observability infra
- Configuration management (use hardcoded constants)
- Multi-LLM / multi-backend / multi-X support
- Graceful degradation for cases that can't happen yet
- Admin UI
- Email / Slack notifications

---

## How v0.1 ships

> The exact entry point the persona uses, the exact output they
> consume.
>
> Example:
>
> > Persona runs `npm run dev` in one terminal and `python -m
> > server` in another. Opens `http://localhost:3000`. Pastes URLs
> > in the form. Clicks Submit. Reads the brief on the same page,
> > copies markdown to clipboard via Cmd+A / Cmd+C.

---

## How v0.1 is verified

> The exact run sequence + the exact criterion check. This is the
> acceptance test.
>
> Example:
>
> > 1. Cold start: `pkill -f server`, `pkill -f vite`. Restart both.
> > 2. Open browser fresh tab, paste 4 known URLs (the p07 corpus).
> > 3. Click Submit. Stopwatch.
> > 4. Verify: brief returns in <45s.
> > 5. Verify: brief contains `Contradictions:` section listing
> >    the $80M/$100M/$120M disagreement.
> > 6. Verify: each [^N] in the brief links to a source URL.
> > 7. Save full session to `runs/YYYY-MM-DD-v0.1.0.md`.
