"""Programmatically prove streaming actually flushes progressively.

We monkeypatch sys.stdout.write to log timestamps for every write, then
run a long-output task and check that the writes come in distinct events
spaced over time (not one big flush at end).
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(r"C:\Users\kleiy\OneDrive\Desktop\ai_agents\.env"))
except ImportError:
    pass

import open_code

# Buffer of (timestamp_since_start, n_chars)
events: list[tuple[float, int]] = []
T0 = None

orig_write = sys.stdout.write
orig_flush = sys.stdout.flush

def tap_write(s):
    global T0
    n = orig_write(s)
    if T0 is None:
        T0 = time.perf_counter()
    events.append((time.perf_counter() - T0, len(s)))
    return n

sys.stdout.write = tap_write  # type: ignore[assignment]

api_key = os.environ.get("GEMINI_API_KEY", "").strip()
if not api_key:
    print("NO API KEY", file=sys.stderr); sys.exit(0)

from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)
cfg = types.GenerateContentConfig(system_instruction="You are a helpful assistant.")
history = [types.Content(role="user", parts=[types.Part.from_text(
    text="Write a 400-word explanation of how TCP/IP works, in simple terms. Just prose, no code."
)])]

T0 = time.perf_counter()
all_parts, fcs, usage = open_code._stream_iter_response(
    client, model="gemini-3.1-flash-lite-preview",
    history=history, config=cfg, verbose=False,
)

sys.stdout.write = orig_write  # restore

# Analyze
print("\n\n=== streaming timing analysis ===", file=sys.stderr)
print(f"Total write events: {len(events)}", file=sys.stderr)
if events:
    first_t = events[0][0]
    last_t = events[-1][0]
    total_chars = sum(n for _, n in events)
    print(f"First write at t+{first_t:.3f}s", file=sys.stderr)
    print(f"Last  write at t+{last_t:.3f}s", file=sys.stderr)
    print(f"Span:           {last_t - first_t:.3f}s", file=sys.stderr)
    print(f"Total chars:    {total_chars}", file=sys.stderr)
    # Count distinct-event-times: writes separated by > 50ms from prior
    distinct_flushes = 1
    for i in range(1, len(events)):
        if events[i][0] - events[i-1][0] > 0.05:
            distinct_flushes += 1
    print(f"Distinct flushes (>50ms gap): {distinct_flushes}", file=sys.stderr)
    if distinct_flushes >= 3 and (last_t - first_t) > 0.3:
        print("VERDICT: TRUE STREAMING (multi-flush, progressive)", file=sys.stderr)
    else:
        print("VERDICT: NOT TRULY STREAMING (one big chunk)", file=sys.stderr)
