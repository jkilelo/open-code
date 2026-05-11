"""Lightweight loop + delayed scheduling (Tier 2 #24).

REPL-local; no daemonization or persistence. Both `/loop` and
`/schedule` block the REPL thread by design — interruptable with
Ctrl-C.

API surface:
  run_loop_with_interval(callback, interval_secs, *, max_iterations=None,
                          sleep=time.sleep) -> SchedulerStats
  run_schedule_delayed(callback, delay_secs, *, sleep=time.sleep)
      -> SchedulerStats

Both take a `callback: Callable[[int], bool]` that runs each
iteration. It returns True to continue, False to stop early.
`int` is the 1-based iteration count.

`sleep` is injectable so probes can run instantaneously.

Why pull these into their own module rather than inline in repl.py:
the loop semantics (interrupt handling, max-iter cap, early-stop
predicate) deserve their own testable surface. The REPL command
handler is then a thin wrapper.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class SchedulerStats:
    """Returned by run_loop_with_interval / run_schedule_delayed."""
    iterations: int = 0
    interrupted: bool = False
    early_stopped: bool = False
    total_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


def run_loop_with_interval(
    callback: Callable[[int], bool],
    interval_secs: float,
    *,
    max_iterations: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> SchedulerStats:
    """Run `callback(iter_n)` repeatedly with `interval_secs` between.

    - Returns when the callback returns False (early stop),
      when max_iterations is reached, or when KeyboardInterrupt fires.
    - If the callback raises any other exception, it's recorded in
      `stats.errors` and the loop continues (so a transient model
      error doesn't kill the whole watch).
    - First iteration runs immediately; sleep happens AFTER each
      iteration before the next.
    """
    stats = SchedulerStats()
    t0 = time.perf_counter()
    n = 0
    try:
        while True:
            if max_iterations is not None and n >= max_iterations:
                break
            n += 1
            stats.iterations = n
            try:
                keep_going = callback(n)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                stats.errors.append(f"iter {n}: {type(exc).__name__}: {exc}")
                keep_going = True
            if not keep_going:
                stats.early_stopped = True
                break
            if max_iterations is not None and n >= max_iterations:
                break
            sleep(interval_secs)
    except KeyboardInterrupt:
        stats.interrupted = True
    stats.total_seconds = time.perf_counter() - t0
    return stats


def run_schedule_delayed(
    callback: Callable[[int], bool],
    delay_secs: float,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> SchedulerStats:
    """Sleep `delay_secs`, then run `callback(1)` once.

    Returns the same stats type as run_loop_with_interval. Honors
    KeyboardInterrupt during the sleep (treated as a cancelled
    schedule — iterations stays 0).
    """
    stats = SchedulerStats()
    t0 = time.perf_counter()
    try:
        sleep(delay_secs)
        stats.iterations = 1
        try:
            callback(1)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            stats.errors.append(f"iter 1: {type(exc).__name__}: {exc}")
    except KeyboardInterrupt:
        stats.interrupted = True
    stats.total_seconds = time.perf_counter() - t0
    return stats


def parse_duration(value: str) -> float:
    """Parse a duration string like '30', '5s', '2m', '1h' into seconds.

    Plain digits = seconds. Suffixes: s, m, h. Raises ValueError on
    junk input.
    """
    v = value.strip().lower()
    if not v:
        raise ValueError("empty duration")
    mult = 1.0
    if v.endswith("s"):
        v = v[:-1]
    elif v.endswith("m"):
        mult = 60.0
        v = v[:-1]
    elif v.endswith("h"):
        mult = 3600.0
        v = v[:-1]
    try:
        n = float(v)
    except ValueError:
        raise ValueError(f"can't parse duration {value!r}")
    # Block inf / nan explicitly. NaN comparisons always return False,
    # so the `< 0` check below silently lets `nan` through. `inf` would
    # pass the `< 0` check and then `time.sleep(inf)` would hang the REPL.
    if not math.isfinite(n):
        raise ValueError(f"duration must be finite; got {value!r}")
    if n < 0:
        raise ValueError(f"duration must be >= 0; got {value!r}")
    return n * mult
