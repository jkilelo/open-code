"""Targeted: does PageRank sum to 1 under personalization?

The Aider/standard formula requires the personalization vector to be a
PROBABILITY distribution over ALL nodes that sums to 1. open-code's
implementation gives `perso_weight = 1/|P|` to nodes in P and `1/n`
to nodes outside P. Total teleport mass = |P|/|P| + (n-|P|)/n = 1 +
(n-|P|)/n != 1.

This probe demonstrates: with personalization on a 5-node graph, the
final PageRank scores do NOT sum to ~1; they sum to roughly 1+frac.
"""
from __future__ import annotations
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pathlib import Path
from repomap import pagerank

# 5-node graph: a->b, b->c, c->d, d->e, e->a (cycle)
nodes = [Path(f"f{i}.py") for i in range(5)]
edges = {nodes[i]: {nodes[(i+1) % 5]} for i in range(5)}

print("=== no personalization ===")
scores = pagerank(edges)
print({str(p.name): round(s, 4) for p, s in scores.items()})
total = sum(scores.values())
print(f"sum = {total:.4f}  (should be ~1.0)")

print("\n=== personalization = {f0, f1} ===")
P = {nodes[0], nodes[1]}
scores = pagerank(edges, personalization=P)
print({str(p.name): round(s, 4) for p, s in scores.items()})
total = sum(scores.values())
print(f"sum = {total:.4f}  (PROPER PageRank should still be ~1.0)")

if total > 1.05 or total < 0.95:
    print(f"\n[FAIL] PageRank under personalization sums to {total:.4f}, not 1.0.")
    print("Root cause (repomap.py): personalization vector must be a")
    print("probability distribution over ALL nodes summing to 1.")
    sys.exit(1)
else:
    print(f"\n[PASS] PageRank sum under personalization = {total:.4f} (within 0.95-1.05)")

# Also: when there's a clear winner the bug usually doesn't *change*
# the ordering on small repos. But test ordering stability:
print("\n=== ordering stability ===")
# 10-node random-ish graph
import hashlib
nodes2 = [Path(f"m{i}.py") for i in range(10)]
edges2 = {}
for i, n in enumerate(nodes2):
    targets = set()
    for j in range(10):
        if i == j:
            continue
        # deterministic pseudo-random connectivity
        h = int(hashlib.sha256(f"{i}-{j}".encode()).hexdigest()[:4], 16)
        if h % 7 == 0:
            targets.add(nodes2[j])
    edges2[n] = targets

ord_none = sorted(pagerank(edges2).items(), key=lambda kv: -kv[1])
ord_p = sorted(pagerank(edges2, personalization={nodes2[0]}).items(), key=lambda kv: -kv[1])
print("top-3 without P:", [p.name for p, _ in ord_none[:3]])
print("top-3 with P={m0}:", [p.name for p, _ in ord_p[:3]])
