"""Repo-map (Aider-style symbol skeleton) for open-code.

Compact "what's in this repo" summary that's prepended to the system
instruction so the model sees the project's symbol surface without
re-reading every file.

v0.13 scope: Python only, stdlib `ast`. No tree-sitter dep yet.
Polyglot extension is v0.14+. The graph + PageRank is hand-rolled
(no networkx) — pure stdlib.

Algorithm:
  1. List tracked files via `git ls-files` (fallback: pathlib glob)
  2. For each *.py file, parse with ast and pull out:
       - Top-level def / class names + signatures
       - Names referenced via Attribute / Name nodes
  3. Build a directed graph:
       file_A -> file_B  iff A references any name that B defines
  4. Run PageRank (~20 iterations of the power method) with
     personalization on the active-task files.
  5. Render the top files' definitions as a skeleton (no bodies).
  6. Cap the output at ~4000 chars to stay below ~1000 model tokens.

Cache: skipped in v0.13 (recompute each invocation; on a 100-file
Python repo this is under 100ms). If we ever support large monorepos,
add a `~/.open-code/cache/<encoded-cwd>/repomap.json` step.
"""
from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


# Default upper bound on the repo-map block (model tokens cost matters).
DEFAULT_MAX_CHARS = 4000
# Don't bother if the repo has fewer than this many files.
MIN_FILES_TO_BOTHER = 3
# Files larger than this are too big to AST-parse cheaply; skip.
MAX_FILE_BYTES = 200_000
# Skip vendored / virtual-env paths.
SKIP_PATH_PARTS = frozenset({
    ".venv", "venv", "env", "node_modules", "__pycache__",
    "site-packages", ".git", ".tox", "build", "dist", ".mypy_cache",
    ".ruff_cache", ".pytest_cache", "_build",
})


@dataclass
class FileSymbols:
    """Definitions and external-name references extracted from one file."""
    path: Path
    definitions: list[str] = field(default_factory=list)   # plain names
    signatures: list[str] = field(default_factory=list)    # one-line `def foo(x): ...`
    references: set[str] = field(default_factory=set)      # names this file mentions


def discover_files(cwd: Path) -> list[Path]:
    """Return tracked .py files in the repo. Tries git first, falls back."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), "ls-files", "*.py"],
            capture_output=True, text=True, timeout=8,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return [
                (cwd / line).resolve()
                for line in proc.stdout.splitlines()
                if line.strip() and not _is_skipped(line)
            ]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    # Fallback: walk
    out: list[Path] = []
    for p in cwd.rglob("*.py"):
        if not _is_skipped(str(p.relative_to(cwd) if p.is_relative_to(cwd) else p)):
            out.append(p.resolve())
    return out


def _is_skipped(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    return any(part in SKIP_PATH_PARTS for part in parts)


def parse_file(path: Path) -> FileSymbols:
    """Use stdlib ast to extract top-level defs/classes + referenced names."""
    syms = FileSymbols(path=path)
    try:
        size = path.stat().st_size
        if size == 0 or size > MAX_FILE_BYTES:
            return syms
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text, filename=str(path))
    except (OSError, SyntaxError, ValueError):
        return syms

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            syms.definitions.append(node.name)
            sig = _func_signature(node)
            syms.signatures.append(sig)
        elif isinstance(node, ast.ClassDef):
            syms.definitions.append(node.name)
            syms.signatures.append(f"class {node.name}:")
            # Include method names as nested signatures (indented one level)
            for sub in ast.iter_child_nodes(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    syms.signatures.append("    " + _func_signature(sub))
                    syms.definitions.append(f"{node.name}.{sub.name}")
    # Walk the whole tree for referenced names (used to build edges).
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            syms.references.add(node.id)
        elif isinstance(node, ast.Attribute):
            syms.references.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                syms.references.add(node.module.split(".")[-1])
            for alias in (node.names or []):
                syms.references.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in (node.names or []):
                syms.references.add(alias.name.split(".")[-1])
    return syms


def _func_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render a single-line function signature without the body."""
    is_async = isinstance(node, ast.AsyncFunctionDef)
    args_parts: list[str] = []
    for a in node.args.args:
        ann = ""
        if a.annotation is not None:
            try:
                ann = f": {ast.unparse(a.annotation)}"
            except Exception:
                ann = ""
        args_parts.append(f"{a.arg}{ann}")
    if node.args.vararg:
        args_parts.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg:
        args_parts.append(f"**{node.args.kwarg.arg}")
    returns = ""
    if node.returns is not None:
        try:
            returns = f" -> {ast.unparse(node.returns)}"
        except Exception:
            returns = ""
    prefix = "async def" if is_async else "def"
    return f"{prefix} {node.name}({', '.join(args_parts)}){returns}: ..."


# ---------------------------------------------------------------------------
# Graph + PageRank
# ---------------------------------------------------------------------------


def build_graph(symbols: list[FileSymbols]) -> dict[Path, set[Path]]:
    """A directed edge from file_A to file_B iff A references a def in B."""
    # Build name -> defining-files index
    name_to_defs: dict[str, set[Path]] = {}
    for fs in symbols:
        for name in fs.definitions:
            # For nested names like Foo.bar, also index `bar`
            for n in (name, name.split(".")[-1]):
                name_to_defs.setdefault(n, set()).add(fs.path)
    edges: dict[Path, set[Path]] = {fs.path: set() for fs in symbols}
    for fs in symbols:
        for ref in fs.references:
            for target in name_to_defs.get(ref, ()):
                if target != fs.path:
                    edges[fs.path].add(target)
    return edges


def pagerank(
    edges: dict[Path, set[Path]],
    *,
    personalization: set[Path] | None = None,
    damping: float = 0.85,
    iterations: int = 20,
) -> dict[Path, float]:
    """Power-method PageRank. O(iterations * (|V| + |E|))."""
    nodes = list(edges.keys())
    if not nodes:
        return {}
    n = len(nodes)
    # Initial: uniform; bumped on personalization set
    perso_weight = 0.0
    if personalization:
        perso_weight = 1.0 / max(len(personalization), 1)
    scores: dict[Path, float] = {}
    for p in nodes:
        if personalization and p in personalization:
            scores[p] = perso_weight
        else:
            scores[p] = 1.0 / n
    # Reverse edges for the propagation step
    incoming: dict[Path, list[Path]] = {p: [] for p in nodes}
    out_degree: dict[Path, int] = {p: len(edges[p]) for p in nodes}
    for src, targets in edges.items():
        for tgt in targets:
            if tgt in incoming:
                incoming[tgt].append(src)
    # Iterate. Dangling nodes (out_degree==0) leak mass; redistribute it.
    for _ in range(iterations):
        dangling_mass = sum(scores[p] for p in nodes if out_degree[p] == 0)
        dangling_share = damping * dangling_mass / n
        new_scores: dict[Path, float] = {}
        for p in nodes:
            tele = (
                (1 - damping) * (perso_weight if personalization and p in personalization
                                 else 1.0 / n)
            )
            contrib = 0.0
            for src in incoming[p]:
                deg = out_degree[src]
                if deg > 0:
                    contrib += scores[src] / deg
            new_scores[p] = tele + damping * contrib + dangling_share
        scores = new_scores
    return scores


# ---------------------------------------------------------------------------
# Renderer + public API
# ---------------------------------------------------------------------------


def render_repomap(
    symbols_by_path: dict[Path, FileSymbols],
    ranked: list[tuple[Path, float]],
    cwd: Path,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Render the top-ranked files as a symbol skeleton, capped at max_chars."""
    out_lines: list[str] = []
    used = 0
    for path, _score in ranked:
        fs = symbols_by_path.get(path)
        if not fs or not fs.signatures:
            continue
        try:
            rel = path.relative_to(cwd)
        except ValueError:
            rel = path
        header = f"\n# {rel}"
        section = [header] + [f"  {s}" for s in fs.signatures]
        block = "\n".join(section) + "\n"
        if used + len(block) > max_chars:
            out_lines.append(
                f"\n# [...repo-map truncated; {len(ranked) - len(out_lines)} "
                f"more files not shown]"
            )
            break
        out_lines.append(block)
        used += len(block)
    return "".join(out_lines).strip()


def build_repomap(
    cwd: Path,
    *,
    task_hint: str | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Top-level entry point: produce the `<repo-map>` block (or empty).

    `task_hint` is an optional snippet of the user's task; we use it to
    personalize PageRank toward files whose path-stems appear in the
    text. (Cheap, no embedding required.)
    """
    files = discover_files(cwd)
    if len(files) < MIN_FILES_TO_BOTHER:
        return ""
    symbols = [parse_file(p) for p in files]
    symbols = [s for s in symbols if s.signatures]  # drop empty parses
    if len(symbols) < MIN_FILES_TO_BOTHER:
        return ""
    edges = build_graph(symbols)
    by_path = {s.path: s for s in symbols}
    personalization = _personalization_from_hint(task_hint, files) if task_hint else None
    scores = pagerank(edges, personalization=personalization)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    body = render_repomap(by_path, ranked, cwd, max_chars=max_chars)
    if not body:
        return ""
    return f"<repo-map>\n{body}\n</repo-map>"


def _personalization_from_hint(hint: str, files: list[Path]) -> set[Path]:
    """Cheap: any file whose stem appears in `hint` is personalized."""
    hint_l = hint.lower()
    out: set[Path] = set()
    for p in files:
        stem = p.stem.lower()
        if stem and stem in hint_l:
            out.add(p)
    return out
