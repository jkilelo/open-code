"""Probe: brutal review B1 — does checkpoints.restore() delete files
that the user has gitignored or that are listed in the shadow repo's
info/exclude?

The reviewer claimed `git clean -fd` (used in `restore`) does NOT honor
the shadow repo's info/exclude. This probe tests two scenarios:

  Scenario A: file is listed in shadow info/exclude (e.g. node_modules/)
    Expected: file survives restore.
  Scenario B: file is gitignored by the user's own .gitignore
    Expected: file survives restore (git clean -fd respects .gitignore
    unless -x is passed).
  Scenario C: file is NOT in any exclude AND NOT gitignored
    Expected: file is removed by restore (legitimately untracked).
"""
from __future__ import annotations
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import checkpoints as CK


if shutil.which("git") is None:
    print("[SKIP] git not on PATH")
    sys.exit(0)


def _setup(base: Path) -> str:
    """Init shadow repo + first snapshot of an empty-ish project."""
    CK.init_shadow_repo(base)
    (base / "a.txt").write_text("v1\n", encoding="utf-8")
    sha, _ = CK.snapshot(base, "v1")
    assert sha
    return sha


# ===========================================================================
# Scenario A: file in shadow info/exclude (e.g. node_modules) survives restore
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    sha = _setup(base)
    # Create a node_modules dir AFTER the snapshot — it's in EXCLUDE_LINES
    (base / "node_modules").mkdir()
    (base / "node_modules" / "package.json").write_text(
        '{"installed":"yes"}', encoding="utf-8",
    )
    # Restore to v1
    ok, msg = CK.restore(base, sha)
    assert ok, f"restore failed: {msg}"
    # node_modules should STILL exist (it's in info/exclude)
    survived = (base / "node_modules" / "package.json").exists()
    if survived:
        print("[PASS] Scenario A: file in shadow info/exclude survives restore")
    else:
        print("[FAIL] Scenario A: shadow info/exclude NOT honored -- "
              "file was DELETED by restore")
        print("       This would confirm reviewer B1.")
        sys.exit(1)


# ===========================================================================
# Scenario B: user's own .gitignore protects file from `git clean -fd`
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    # Create a user .gitignore BEFORE init/snapshot so it's part of v1
    (base / ".gitignore").write_text("dist/\n", encoding="utf-8")
    sha = _setup(base)
    # Now create a "dist/" dir with content AFTER the snapshot
    (base / "dist").mkdir()
    (base / "dist" / "build-artifact.bin").write_text("PRECIOUS",
                                                      encoding="utf-8")
    # Restore to v1
    ok, msg = CK.restore(base, sha)
    assert ok, f"restore failed: {msg}"
    # The reviewer's B1 claim: dist/build-artifact.bin gets deleted.
    survived = (base / "dist" / "build-artifact.bin").exists()
    if survived:
        print("[PASS] Scenario B: user .gitignore protects from `git clean -fd`")
    else:
        print("[FAIL] Scenario B: user-gitignored file DELETED by restore")
        print("       This CONFIRMS reviewer B1.")
        sys.exit(1)


# ===========================================================================
# Scenario C: ordinary untracked file IS deleted (correct behavior)
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    sha = _setup(base)
    # An ordinary new file, not in any exclude
    (base / "new.txt").write_text("added after v1", encoding="utf-8")
    ok, _ = CK.restore(base, sha)
    assert ok
    survived = (base / "new.txt").exists()
    assert not survived, \
        "ordinary untracked file should have been removed by restore"
    print("[PASS] Scenario C: ordinary untracked file is removed (correct)")


# ===========================================================================
# Scenario D: file in .open-code/ (our own state) MUST survive
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    sha = _setup(base)
    # Simulate something we wrote to .open-code/ between snapshots —
    # e.g. settings.local.json, session JSONLs.
    (base / ".open-code" / "settings.local.json").write_text(
        '{"private": true}', encoding="utf-8",
    )
    ok, _ = CK.restore(base, sha)
    assert ok
    survived = (base / ".open-code" / "settings.local.json").exists()
    if survived:
        print("[PASS] Scenario D: .open-code/ contents survive restore")
    else:
        print("[FAIL] Scenario D: .open-code/ DELETED — would wipe our own state")
        sys.exit(1)


print("\nOK -- restore-safety probes passed.")
