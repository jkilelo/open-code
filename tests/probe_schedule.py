"""Probe: /loop + /schedule scheduler (Tier 2 #24)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import schedule as SC


# ===========================================================================
# Test 1: parse_duration accepts plain seconds + s/m/h suffixes
# ===========================================================================
assert SC.parse_duration("30") == 30.0
assert SC.parse_duration("30s") == 30.0
assert SC.parse_duration("5m") == 300.0
assert SC.parse_duration("1h") == 3600.0
assert SC.parse_duration("2.5m") == 150.0
assert SC.parse_duration("0") == 0.0
for bad in ("", "abc", "-5", "5x", "h", "inf", "infinity", "nan", "-inf"):
    raised = False
    try:
        SC.parse_duration(bad)
    except ValueError:
        raised = True
    assert raised, f"parse_duration({bad!r}) should have raised"
print("[PASS] parse_duration handles s/m/h suffixes and rejects junk (incl. inf/nan)")


# ===========================================================================
# Test 2: run_loop_with_interval honors max_iterations + injected sleep
# ===========================================================================
sleeps: list[float] = []
calls: list[int] = []
def _sleep(s: float) -> None:
    sleeps.append(s)
def _cb(n: int) -> bool:
    calls.append(n)
    return True  # never stop early

stats = SC.run_loop_with_interval(_cb, 0.5, max_iterations=3, sleep=_sleep)
assert stats.iterations == 3
assert calls == [1, 2, 3]
# Sleep between iters: we sleep AFTER each iter except the last one
# that's about to hit the cap. With max=3 and the cap-check after sleep,
# the implementation sleeps 2 times (between 1→2 and 2→3).
assert len(sleeps) == 2, f"expected 2 sleeps; got {len(sleeps)}: {sleeps}"
assert all(s == 0.5 for s in sleeps)
assert not stats.interrupted
assert not stats.early_stopped
print("[PASS] run_loop_with_interval: max_iterations cap + sleep injection")


# ===========================================================================
# Test 3: callback returning False stops early
# ===========================================================================
def _cb_two(n: int) -> bool:
    return n < 2  # iter 1 returns True (keep going), iter 2 returns False
stats = SC.run_loop_with_interval(_cb_two, 0.5, max_iterations=10, sleep=lambda s: None)
assert stats.iterations == 2
assert stats.early_stopped is True
assert stats.interrupted is False
print("[PASS] callback returning False triggers early-stop")


# ===========================================================================
# Test 4: KeyboardInterrupt during callback is caught + flagged
# ===========================================================================
def _cb_boom(n: int) -> bool:
    if n == 3:
        raise KeyboardInterrupt("user pressed Ctrl-C")
    return True
stats = SC.run_loop_with_interval(_cb_boom, 0.1, max_iterations=10,
                                  sleep=lambda s: None)
assert stats.interrupted is True
assert stats.iterations == 3
print("[PASS] KeyboardInterrupt mid-callback flagged as interrupted")


# ===========================================================================
# Test 5: non-KeyboardInterrupt exception is recorded but loop continues
# ===========================================================================
def _cb_flaky(n: int) -> bool:
    if n == 2:
        raise RuntimeError("transient")
    return n < 4
stats = SC.run_loop_with_interval(_cb_flaky, 0.0, max_iterations=10,
                                  sleep=lambda s: None)
assert stats.iterations == 4  # iter 4 returned False, early-stopping
assert len(stats.errors) == 1
assert "transient" in stats.errors[0]
assert "RuntimeError" in stats.errors[0]
assert stats.early_stopped is True
assert stats.interrupted is False
print("[PASS] non-KeyboardInterrupt exception recorded; loop continues")


# ===========================================================================
# Test 6: run_schedule_delayed sleeps once then runs once
# ===========================================================================
sleeps = []
ran: list[int] = []
def _sleep_capture(s: float) -> None:
    sleeps.append(s)
def _cb_run(n: int) -> bool:
    ran.append(n)
    return False  # ignored by run_schedule_delayed

stats = SC.run_schedule_delayed(_cb_run, 10.0, sleep=_sleep_capture)
assert sleeps == [10.0], f"expected one 10s sleep; got {sleeps}"
assert ran == [1]
assert stats.iterations == 1
assert not stats.interrupted
print("[PASS] run_schedule_delayed sleeps once then runs once")


# ===========================================================================
# Test 7: KeyboardInterrupt during the pre-callback sleep cancels cleanly
# ===========================================================================
def _sleep_raise(s: float) -> None:
    raise KeyboardInterrupt("Ctrl-C while waiting")
def _never(n: int) -> bool:
    raise AssertionError("callback should NOT run")
stats = SC.run_schedule_delayed(_never, 5.0, sleep=_sleep_raise)
assert stats.interrupted is True
assert stats.iterations == 0
print("[PASS] KeyboardInterrupt during pre-callback sleep cancels")


print("\nOK -- schedule probes passed.")
