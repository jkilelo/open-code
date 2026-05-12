"""High-performance BM25 search over the agent library.

Why this exists:
The model can have hundreds of agents (hand-written + autobuilt).
Linear scans + substring matches don't scale and don't rank well.
BM25 (Robertson-Sparck Jones, with Salton's TF normalization) is
the IR baseline that consistently beats naive scoring on short
document collections like agent descriptions.

Math (the form used here):

    score(D, Q) = sum_{q in Q} IDF(q) * (f(q,D) * (k1+1))
                                       / (f(q,D) + k1*(1 - b + b*|D|/avgdl))

    IDF(q) = ln((N - n(q) + 0.5) / (n(q) + 0.5) + 1)

Defaults (k1=1.5, b=0.75) are the Lucene / Elasticsearch values
that hold up across most text retrieval tasks.

Index is rebuilt on every search() call when any underlying file's
mtime changes -- cheap because the agent file count is bounded by
the user's library size (hundreds, not millions). For larger
libraries we'd add a persistent inverted index, but that's premature
at this scale.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

# Conservative stopword list: only obvious noise that BM25 IDF would
# struggle with at small N anyway. Stays short to avoid over-pruning.
STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "in", "is", "it", "its", "of", "on", "or", "that",
    "the", "this", "to", "was", "were", "will", "with",
})

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase + alphanumeric-split + drop length<=1 + drop stopwords.

    Deterministic and pure. The single chokepoint for tokenization
    in this module so changes ripple predictably.
    """
    if not text:
        return []
    out: list[str] = []
    for m in _TOKEN_RE.finditer(text.lower()):
        t = m.group(0)
        if len(t) <= 1 or t in STOPWORDS:
            continue
        out.append(t)
    return out


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


@dataclass
class AgentDoc:
    """One indexable agent record. Cheap to construct; all fields plain."""
    name: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    domain: str = ""
    path: Path | None = None
    source: str = "user"  # "user" (hand-written) | "autobuild" | "plugin"
    mtime: float = 0.0
    extras: dict[str, Any] = field(default_factory=dict)

    def search_text(self) -> str:
        """Concatenation of every searchable field. Order doesn't
        affect BM25 scores (bag-of-words) but matters for tie-breaks
        in tokenize order."""
        parts = [
            self.name,
            self.description,
            self.domain,
            " ".join(self.capabilities),
        ]
        return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# BM25 index
# ---------------------------------------------------------------------------


class BM25Index:
    """In-memory BM25 over a list of AgentDoc.

    Build cost: O(total_tokens). Search cost: O(|query| * |postings_for_term|).
    For ~1000 agents the index occupies a few hundred KB and a search
    runs in well under a millisecond.
    """

    def __init__(self, agents: list[AgentDoc], k1: float = 1.5,
                 b: float = 0.75) -> None:
        self.agents = list(agents)
        self.k1 = k1
        self.b = b
        self._tokens: list[list[str]] = []
        self._doc_len: list[int] = []
        # Inverted index: token -> list of (doc_id, term_frequency)
        self._postings: dict[str, list[tuple[int, int]]] = {}
        # Number of docs containing each token
        self._df: dict[str, int] = {}
        self._n_docs = 0
        self._avgdl = 1.0
        self._build()

    def _build(self) -> None:
        self._tokens = [tokenize(a.search_text()) for a in self.agents]
        self._doc_len = [len(toks) for toks in self._tokens]
        self._n_docs = len(self._tokens)
        self._avgdl = (
            sum(self._doc_len) / self._n_docs if self._n_docs else 1.0
        ) or 1.0
        # Build posting lists + document frequencies.
        # For each doc, count term frequencies then accumulate.
        postings: dict[str, list[tuple[int, int]]] = {}
        df: dict[str, int] = {}
        for doc_id, toks in enumerate(self._tokens):
            tf_local: dict[str, int] = {}
            for t in toks:
                tf_local[t] = tf_local.get(t, 0) + 1
            for t, tf in tf_local.items():
                postings.setdefault(t, []).append((doc_id, tf))
                df[t] = df.get(t, 0) + 1
        self._postings = postings
        self._df = df

    def _idf(self, term: str) -> float:
        n_q = self._df.get(term, 0)
        if n_q == 0:
            return 0.0
        # The "+1" inside the log keeps IDF non-negative for terms
        # appearing in more than half the corpus.
        return math.log((self._n_docs - n_q + 0.5) / (n_q + 0.5) + 1.0)

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        score_threshold: float = 0.0,
    ) -> list[tuple[AgentDoc, float]]:
        """Return up to `limit` (AgentDoc, score) pairs ranked by BM25.

        score_threshold filters out weak matches. Default 0 returns
        anything that has any matching term; callers may want a
        higher threshold (e.g. 0.5) before deciding to route.
        """
        if not self.agents:
            return []
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        scores = [0.0] * self._n_docs
        for qt in q_tokens:
            postings = self._postings.get(qt)
            if not postings:
                continue
            idf = self._idf(qt)
            if idf <= 0:
                continue
            for doc_id, tf in postings:
                # Standard BM25 term contribution.
                dl = self._doc_len[doc_id]
                norm = 1.0 - self.b + self.b * dl / self._avgdl
                contribution = idf * tf * (self.k1 + 1.0) / (
                    tf + self.k1 * norm
                )
                scores[doc_id] += contribution
        # Rank and threshold.
        ranked = [
            (self.agents[i], s)
            for i, s in sorted(
                enumerate(scores), key=lambda x: -x[1],
            )
            if s > score_threshold
        ]
        return ranked[:limit]


# ---------------------------------------------------------------------------
# Discovery + caching
# ---------------------------------------------------------------------------


AUTOBUILD_AGENTS_REL = ".open-code/autobuild-agents"
USER_AGENTS_REL = ".open-code/agents"


def _read_agent_file(path: Path, source: str) -> AgentDoc | None:
    """Parse a single .md agent file. Returns None on malformed input.

    The frontmatter parser is intentionally minimal (keep it local
    to this module so a future change to subagents.py's parser doesn't
    break the search index). Recognized fields:
      name           required
      description    fed to BM25
      domain         fed to BM25 (single-word category)
      capabilities   list of keywords fed to BM25
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            raw = text[3:end].lstrip("\n").rstrip()
            body = text[end + 4:].lstrip("\n")
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip()
    name = fm.get("name", "").strip() or path.stem
    if not name:
        return None
    desc = fm.get("description", "").strip()
    domain = fm.get("domain", "").strip()
    caps_raw = fm.get("capabilities", "").strip()
    caps: list[str] = []
    if caps_raw:
        s = caps_raw.lstrip("[").rstrip("]")
        caps = [p.strip().strip("'\"") for p in s.split(",") if p.strip()]
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return AgentDoc(
        name=name,
        description=desc,
        capabilities=caps,
        domain=domain,
        path=path,
        source=source,
        mtime=mtime,
        extras={"body": body},
    )


def discover_indexable_agents(cwd: Path) -> list[AgentDoc]:
    """Scan both `.open-code/agents/` and `.open-code/autobuild-agents/`.

    Hand-written agents take precedence on name collision -- the
    autobuild path can't shadow a deliberate user agent.
    """
    out: dict[str, AgentDoc] = {}
    autobuild = cwd / AUTOBUILD_AGENTS_REL
    if autobuild.exists() and autobuild.is_dir():
        for f in sorted(autobuild.glob("*.md")):
            doc = _read_agent_file(f, source="autobuild")
            if doc is not None:
                out[doc.name] = doc
    user = cwd / USER_AGENTS_REL
    if user.exists() and user.is_dir():
        for f in sorted(user.glob("*.md")):
            doc = _read_agent_file(f, source="user")
            if doc is not None:
                out[doc.name] = doc  # user shadows autobuild
    return list(out.values())


# Process-local cache. The index gets rebuilt when any underlying file
# mtime changes OR a new file appears. Cheap: stat() per file is fast.
_INDEX_CACHE: dict[str, tuple[BM25Index, list[float]]] = {}


def _signature(agents: list[AgentDoc]) -> list[float]:
    """A change-detection signature: sorted mtimes + count. Cheap
    enough that we can recompute on every search call."""
    return sorted([a.mtime for a in agents]) + [float(len(agents))]


def get_index(cwd: Path) -> BM25Index:
    """Return an up-to-date BM25 index for this CWD's agent library.

    Reuses the cached index when the file mtimes haven't changed.
    """
    key = str(cwd.resolve())
    agents = discover_indexable_agents(cwd)
    sig = _signature(agents)
    cached = _INDEX_CACHE.get(key)
    if cached is not None and cached[1] == sig:
        return cached[0]
    idx = BM25Index(agents)
    _INDEX_CACHE[key] = (idx, sig)
    return idx


def invalidate_cache(cwd: Path | None = None) -> None:
    """Drop the cached index for a CWD (or all CWDs if None).

    Called by agent_builder after writing a new file so the next
    search picks it up without waiting for the natural mtime check.
    """
    if cwd is None:
        _INDEX_CACHE.clear()
        return
    _INDEX_CACHE.pop(str(cwd.resolve()), None)


def search_agents(
    cwd: Path,
    query: str,
    *,
    limit: int = 5,
    score_threshold: float = 0.0,
) -> list[tuple[AgentDoc, float]]:
    """Convenience: get_index + search in one call."""
    return get_index(cwd).search(
        query, limit=limit, score_threshold=score_threshold,
    )
