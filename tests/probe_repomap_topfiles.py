"""Probe: does the PageRank fix actually CHANGE rankings in real repos?

If the fix is a no-op for the common case, the v0.13 claim that
"repomap produces useful symbol skeletons" was suspect -- the
algorithm bug wasn't materially impacting results. If the fix
dramatically changes top files, the prior repomap was lying.
"""
from __future__ import annotations
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pathlib import Path
from repomap import build_repomap, discover_files, parse_file, build_graph, pagerank


root = pathlib.Path(__file__).resolve().parent.parent
files = discover_files(root)
print(f"discovered {len(files)} files in {root}")

symbols_by_path = {}
for f in files:
    syms = parse_file(f)
    if syms:
        symbols_by_path[syms.path] = syms

edges = build_graph(list(symbols_by_path.values()))
print(f"edges built; {len(edges)} nodes")

# Current ranking (with fixed PageRank)
ranked = sorted(pagerank(edges).items(), key=lambda kv: -kv[1])
print(f"\n=== TOP 10 (current pagerank -- fixed) ===")
for p, score in ranked[:10]:
    try:
        rel = p.relative_to(root)
    except ValueError:
        rel = p
    print(f"  {score:.4f}  {rel}")

# Now with personalization on the README (typical usage)
readme_paths = [p for p in edges if p.name.lower() == "readme.md"]
some_paths = [p for p in edges if p.name in ("tools.py", "patches.py")]
P = set(some_paths)
print(f"\n=== TOP 10 (personalized on {[p.name for p in P]}) ===")
ranked2 = sorted(pagerank(edges, personalization=P).items(), key=lambda kv: -kv[1])
for p, score in ranked2[:10]:
    try:
        rel = p.relative_to(root)
    except ValueError:
        rel = p
    print(f"  {score:.6e}  {rel}")

# Confirm propagation actually happens:
nonzero_off_P = sum(1 for p, s in ranked2 if s > 1e-9 and p not in P)
print(f"\nnon-zero mass on nodes NOT in P: {nonzero_off_P}")

# Sum check
sum1 = sum(s for _, s in ranked)
sum2 = sum(s for _, s in ranked2)
print(f"\nsum (no personalization): {sum1:.4f}")
print(f"sum (with personalization): {sum2:.4f}")
assert abs(sum1 - 1.0) < 0.05, f"non-personalized sum {sum1} not ~1.0"
assert abs(sum2 - 1.0) < 0.05, f"personalized sum {sum2} not ~1.0"
print("\n[PASS] both rankings normalize to 1.0")
