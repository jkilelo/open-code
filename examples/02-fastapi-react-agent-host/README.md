# Worked example 02 -- FastAPI/React/SQLite/Tailwind agent host

This is what Claude WOULD do if a user copied the kit into a new
project and prompted:

> Build a full-stack FastAPI + SQLite + Tailwind + React app that
> hosts AI agents for multiple use cases.

The example is illustrative -- Claude doesn't actually build it here.
But every step shows the kit's loop in action.

---

## Session 1 -- extraction (no code)

The prompt names a stack and a domain. It doesn't name a persona.

Claude's response:

> I'm operating under the persona-mvp-kit standard. Before I write
> any code, I need to extract personas. The prompt names FastAPI +
> React + SQLite + Tailwind for an "AI agent host," but doesn't
> say who the host is for or what the agents do. Four questions:
>
> 1. **Who runs the agents?** Internal team (which department)?
>    External customers? End users?
>
> 2. **What's the FIRST agent the host serves?** Pick the most
>    valuable one. "Summarize 10 articles into a brief?" "Draft
>    sales emails?" "Scan logs for anomalies?" Different agents
>    mean wildly different apps.
>
> 3. **What does that user do today instead?** This anchors the
>    "outperforms" bar.
>
> 4. **What does success look like on a typical Tuesday?** Concrete
>    output, concrete time saved, concrete consumption pattern
>    (do they paste to email? upload to a wiki? share via Slack?).

User responds:

> Internal marketing analysts. Each agent helps with a different
> part of their workflow. The first one's a "competitor brief"
> agent -- give it 10 URLs of competitor news, get a 5-bullet brief.
> Currently they skim articles in browser tabs, copy-paste notes
> into Notion, takes about 25 minutes per round. Goal: <90 seconds
> from URL paste to brief in clipboard, ready to drop into a
> Slack channel.

Claude writes `personas.md`:

```markdown
# Personas

## Primary persona -- v0.1 ships

### Sam Park -- Marketing Analyst, mid-market SaaS company

**Daily pain:** every Monday + Wednesday morning, Sam compiles a
"competitor pulse" by skimming ~10 news articles from a list his
PM sends. He opens each in a browser tab, reads, copy-pastes notes
into a Notion doc, then summarizes the doc into a 5-bullet Slack
post for the GTM channel. Average round: 25 min. He misses items
when articles use jargon he doesn't recognize.

**Primary workflow:** Paste 10 URLs into a form, get a 5-bullet
markdown brief with citations linking back to source URLs, copy
to Slack.

**Success criterion:** <90s end-to-end. Each bullet ends with
`[^N]` linking to the source URL. Bullets cover the most-cited /
most-novel claims across the 10 articles. Output is markdown
ready for Slack paste.

**What "no" looks like:** if it takes >2 min, Sam keeps doing it
manually. If a bullet is unsupported by any URL, he doesn't trust
the tool. If pasting into Slack mangles the markdown, he switches
back to manual.

## Secondary -- v0.2

### Devin Liu -- Marketing Ops Manager
[runs the ad-spend-analysis agent: parses GA4 export + paid
spreadsheets to find anomalies -- different workflow, different
agent, different slice]

## Tertiary -- v0.3+

### Jordan Singh -- Content Writer
[blog-post-draft agent -- different workflow, different slice]
```

Claude shows the file. User confirms.

---

## Session 1 (continued) -- MVP spec

Claude writes `mvp-spec.md`:

```markdown
# MVP spec -- v0.1

## Persona shipped
Sam Park (marketing analyst). See personas.md.

## Success criterion
"Sam pastes 10 URLs into a single web form, clicks 'summarize.'
Within 90s, the page shows a 5-bullet brief, each bullet ending
with `[^N]` citation linking to the source URL. Sam copies the
markdown via Cmd+A / Cmd+C and pastes into Slack -- markdown
formatting survives. End-to-end on a typical Tuesday: <90s vs
his current ~25 minutes."

## Smallest tech stack
- **FastAPI** -- Sam's workflow is "POST 10 URLs, get markdown
  back." Long-lived service. FastAPI's auto-OpenAPI gives a
  built-in "try it" UI for free.
- **SQLite** -- store {brief_id, urls (JSON array), output, created_at}.
  Single user, <100MB ever. Single process.
- **Gemini 1.5 Flash** -- the user has a key configured. Single
  model in v0.1.
- **httpx + readability-lxml** -- fetch + extract main article text
  from each URL. Two libraries because we need (a) HTTP client and
  (b) HTML->text. Both small, both stable.
- **React + Vite** (one page, no router) -- Sam needs a paste-form
  and a results area. No router because there's only one page.
- **Tailwind defaults** -- Sam isn't design-sensitive; brand
  guidelines TBD. Default Tailwind keeps the UI accessible.
- **No ORM.** Raw SQL via stdlib `sqlite3`. The schema is one table
  with five columns; an ORM is overhead.
- **No state management.** `useState` in App.tsx is enough.

## OUT of v0.1
- Auth -- Sam is the sole user; runs `npm run dev` + `python -m server`
- Database migrations -- one initial schema, edited in place
- Deployment / Docker / CI -- Sam runs locally
- Multiple agents -- only "competitor brief" agent in v0.1
- Multi-LLM -- Gemini 1.5 Flash hardcoded
- Streaming responses -- sync is fine at <90s
- URL fetching with JS rendering -- readability-lxml only;
  JS-heavy sites fail loudly with "could not extract text from
  URL N -- paste body as fallback"
- File / PDF / image inputs -- URLs only
- Scheduled / triggered runs -- Sam clicks Submit
- Rate limiting / retries / observability
- Mobile UI -- desktop only (Sam works on laptop)
- Dark mode

## How v0.1 ships
Sam clones repo, runs `python -m server` in one terminal and
`npm run dev` in another. Opens `http://localhost:5173`. Pastes 10
URLs (one per line) in the textarea. Clicks Submit. Sees brief
on the same page. Copies markdown to Slack.

## How v0.1 is verified
1. From cold start: kill processes, restart both.
2. Fresh browser tab. Paste 10 URLs from a known fixture corpus.
3. Stopwatch. Click Submit.
4. Verify: brief returns in <90s.
5. Verify: brief has exactly 5 bullets each ending with `[^N]`.
6. Verify: each `[^N]` links to a URL from the input set.
7. Verify: copy markdown, paste into Slack, formatting survives
   (bullets render, links are clickable).
8. Save full session to `runs/YYYY-MM-DD-v0.1.0.md`.
```

User confirms.

---

## Session 2 -- build the smallest e2e slice

Claude builds in order:

### Step 1: backend that returns hardcoded brief

```python
# server/main.py
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class BriefRequest(BaseModel):
    urls: list[str]

class BriefResponse(BaseModel):
    markdown: str

@app.post("/briefs")
def post_brief(req: BriefRequest) -> BriefResponse:
    # TEMPORARY -- returns hardcoded markdown so the frontend has
    # something real to render against. Replaced in step 3.
    return BriefResponse(markdown=f"# Brief\n\n- (placeholder for {len(req.urls)} urls)")
```

Run `uvicorn server.main:app --reload`. Hit it via curl. Real
response, real Pydantic, real port.

### Step 2: frontend that POSTs and renders

```tsx
// app/src/App.tsx
import { useState } from 'react';

export default function App() {
  const [urls, setUrls] = useState('');
  const [brief, setBrief] = useState('');
  const [loading, setLoading] = useState(false);
  const onSubmit = async () => {
    setLoading(true);
    const r = await fetch('/api/briefs', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({urls: urls.split('\n').filter(Boolean)})
    });
    const j = await r.json();
    setBrief(j.markdown);
    setLoading(false);
  };
  return (
    <main className="p-6 max-w-3xl mx-auto">
      <textarea className="w-full h-48 border p-2 rounded" value={urls}
        onChange={e => setUrls(e.target.value)}
        placeholder="One URL per line" />
      <button onClick={onSubmit}
        className="mt-2 bg-blue-600 text-white px-4 py-2 rounded">
        {loading ? 'Working...' : 'Summarize'}
      </button>
      <pre className="mt-4 whitespace-pre-wrap">{brief}</pre>
    </main>
  );
}
```

Vite proxy to backend. Run both. Paste URLs. See placeholder render.
**Real e2e wiring established.**

### Step 3: replace placeholder with real fetching + LLM

```python
# server/brief.py
import httpx
from readability import Document
from google import genai
from .schemas import BriefRequest, BriefResponse

def fetch_article_text(url: str) -> str:
    r = httpx.get(url, timeout=20, follow_redirects=True)
    r.raise_for_status()
    return Document(r.text).summary()

PROMPT = """
You are summarizing competitor news for a marketing analyst.
Given the N source articles below, produce exactly 5 bullets
covering the most-cited or most-novel claims across them. Each
bullet MUST end with [^N] where N is the source index.

Output in markdown, ready to paste into Slack.

ARTICLES:
{articles}
"""

def generate_brief(req: BriefRequest, llm: genai.Client) -> str:
    articles = []
    for i, url in enumerate(req.urls, 1):
        try:
            text = fetch_article_text(url)
            articles.append(f"[{i}] URL={url}\n{text[:3000]}")
        except Exception as exc:
            articles.append(f"[{i}] URL={url}\n(could not fetch: {exc})")
    prompt = PROMPT.format(articles="\n\n---\n\n".join(articles))
    resp = llm.models.generate_content(model="gemini-1.5-flash", contents=prompt)
    return resp.text
```

Wire into `/briefs` endpoint. Add `dotenv` to load `GEMINI_API_KEY`.

### Step 4: persistence

```python
# server/store.py
import sqlite3, json
from datetime import datetime, timezone
DB = sqlite3.connect("briefs.db", check_same_thread=False)
DB.execute("""CREATE TABLE IF NOT EXISTS briefs(
    id TEXT PRIMARY KEY, urls TEXT, output TEXT, created_at TEXT)""")
DB.commit()

def save_brief(brief_id, urls, output):
    DB.execute(
        "INSERT INTO briefs VALUES (?, ?, ?, ?)",
        (brief_id, json.dumps(urls), output,
         datetime.now(timezone.utc).isoformat()))
    DB.commit()

def list_briefs():
    rows = DB.execute(
        "SELECT id, urls, output, created_at FROM briefs ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    return [{"id": r[0], "urls": json.loads(r[1]), "output": r[2], "created_at": r[3]} for r in rows]
```

Wire `/briefs` to call `save_brief`; add `GET /briefs` for history.

### Step 5: history panel

Add a `<HistoryList>` component that fetches `/api/briefs` on mount
and renders the last 20 with timestamps.

### Step 6: CSS polish (Tailwind defaults)

Spacing, font sizes, a clear "loading..." state during the LLM
call. ~30 lines of Tailwind classes.

That's the slice. Total: ~250 lines server-side, ~120 lines
frontend, one HTML index, one Vite config.

---

## Session 3 -- run as Sam

Claude opens both terminals, opens `localhost:5173`, pastes 10
real URLs from a marketing news source, hits Submit, stopwatch.

`runs/2026-05-12-v0.1.0.md`:

```markdown
# Run as Sam -- 2026-05-12 v0.1.0

## Setup
Cold start: `pkill -f vite && pkill -f uvicorn`. Restarted both.

## Inputs
10 competitor news URLs (techcrunch, theverge, businessinsider,
etc.) saved in /tmp/sam-urls.txt.

## Run
- Paste URLs to textarea. Click Submit. Stopwatch starts.
- 12s: spinner showing "Working..."
- 73s: brief renders.
- Total wall-clock: 73s.

## Output (verbatim)
- Acme Corp announced $100M Series C, led by Andreessen, doubling
  their EU footprint [^1]
- BetaCo released GPT-4-class on-prem model targeting regulated
  industries [^2]
- ... [3 more bullets]

## Five questions
1. Workflow completed without intervention. [OK]
2. Criterion met:
   - [OK] <90s (73s actual)
   - [OK] 5 bullets each ending in [^N]
   - [OK] Each [^N] links to a URL in the input set
   - [OK] Markdown pastes cleanly into Slack (verified)
3. Faked: nothing significant. URL fetching uses real httpx, LLM
   is real Gemini, DB is real SQLite.
4. Gaps observed:
   - One URL (theverge) had a soft paywall and readability
     extracted only the meta description (~80 chars). The
     bullet citing [^4] references that URL but the underlying
     content is thin. Sam would notice on click-through. Add
     an "extracted text was suspiciously short -- paste body
     instead?" warning at the URL level.
   - History panel works but doesn't show enough URL info to
     re-find a brief from yesterday. Show first URL or a
     user-set title.
5. Yes, Sam would use this tomorrow. The thin-content gap is
   real but he can paste the body manually for paywalled sites.
   The history-disambiguation gap is mild. Both go to gap-log.md
   for v0.1.1.
```

[OK] Primary persona criterion concretely met. v0.1.0 is shippable.

---

## Session 4 -- ratchet (v0.1.1)

Address the two gaps in two commits, each with the persona quoted:

```
Sam: warn when URL extraction returns suspiciously short text

Persona pain: the Verge soft-paywalled article gave readability-lxml
only the meta description (~80 chars). The brief bullet that cited
[^4] was based on that 80 chars. Sam clicks through, sees the bullet
doesn't match the article content. Trust collapses.

Root cause: extraction failure was silent -- empty/short text was
passed to the LLM, which made up a plausible-sounding summary.

Fix: in fetch_article_text, if extracted body is <200 chars OR
contains <30 distinct words, raise ShortContentError. The endpoint
catches it and adds a warning to the article block in the prompt:
"[N] URL=... -- could not extract main content (paywall? JS?). Skip
this article unless explicitly requested." LLM now omits weak
bullets and explicitly says so.

Verification: re-run with same 10 URLs. Brief now has 4 strong
bullets and one explicit "[^4] not summarized -- paywall detected."
Sam trusts it.
```

```
Sam: history panel shows first URL of each brief for disambiguation
[similar shape]
```

Tag `v0.1.1`.

---

## Session 5 -- adding Devin (v0.2)

After v0.1.x is solid for Sam, the user prompts:

> Now add the ad-spend anomaly agent for Devin.

Claude reads `personas.md` Sec. Devin, writes `mvp-spec-v0.2.md` for
his workflow, builds the slice. Sam's slice is unchanged. Each agent
is its own vertical; the host frame (FastAPI app, React shell,
SQLite db, common UI) is the SAME -- extended, not replaced.

Notably, what's NOT happening:

- No "let me refactor the agent system to be pluggable" -- earned by
  the second agent, not speculated for the first.
- No "let me extract a base Agent class" -- earned by THIRD agent.
- No "let me add an agent registry pattern" -- earned by N-many.

Each abstraction earns its existence by N=2 minimum.

---

## What this example illustrates

- **The first prompt extracts personas.** No code in session 1.
- **The MVP spec is short.** 4 sections, persona-justified.
- **Build is vertical.** Backend -> frontend -> wired -> polish, in
  steps where each ends with a runnable workflow.
- **Run as the persona** is the acceptance test, not unit tests.
- **Gaps go to gap-log; commits close them one at a time.**
- **Adding the second persona doesn't break the first.** Each
  persona is its own ratchet.
