"""Probe: shadow-git checkpoints (Tier 2 #11).

Tests the shadow-git module in isolation, then verifies the
SessionStore.append_checkpoint event semantics. Live REPL integration
(slash commands) is covered by hand-tested evidence in the runs/ doc.
"""
from __future__ import annotations
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import checkpoints as CK
import sessions as SX


_HAVE_GIT = shutil.which("git") is not None


def _skip_if_no_git(label: str) -> bool:
    if not _HAVE_GIT:
        print(f"[SKIP] {label}: git binary not on PATH")
        return True
    return False


# ===========================================================================
# Test 1: init_shadow_repo is idempotent
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    if not _skip_if_no_git("init idempotent"):
        ok1, msg1 = CK.init_shadow_repo(base)
        assert ok1, f"init failed: {msg1}"
        assert CK.is_initialized(base)
        assert (base / ".open-code" / "checkpoints.git" / "HEAD").exists()
        # Calling again must be a no-op success
        ok2, msg2 = CK.init_shadow_repo(base)
        assert ok2
        assert "already initialized" in msg2
        print("[PASS] init_shadow_repo idempotent")


# ===========================================================================
# Test 2: snapshot + rev-parse + list_checkpoints
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    if not _skip_if_no_git("snapshot + list"):
        ok, _ = CK.init_shadow_repo(base)
        assert ok
        (base / "a.txt").write_text("hello\n", encoding="utf-8")
        sha1, msg1 = CK.snapshot(base, "first snapshot")
        assert sha1, f"snapshot failed: {msg1}"
        assert len(sha1) == 40, f"expected full 40-char sha, got {len(sha1)}"
        # A second snapshot with no changes -- must still produce a NEW sha
        # because we pass --allow-empty
        sha2, _ = CK.snapshot(base, "no-change snapshot")
        assert sha2, "second snapshot returned None"
        assert sha2 != sha1, "expected different sha for --allow-empty commit"
        # Make a change + third snapshot
        (base / "a.txt").write_text("hello\nworld\n", encoding="utf-8")
        sha3, _ = CK.snapshot(base, "changed snapshot")
        assert sha3 and sha3 != sha2
        rows = CK.list_checkpoints(base, limit=10)
        assert len(rows) == 3, f"expected 3 checkpoints, got {len(rows)}"
        assert rows[0]["sha"] == sha3  # newest first
        assert rows[1]["sha"] == sha2
        assert rows[2]["sha"] == sha1
        assert all("label" in r for r in rows)
        print("[PASS] snapshot + list (3 checkpoints, newest first)")


# ===========================================================================
# Test 3: restore round-trip
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    if not _skip_if_no_git("restore round-trip"):
        CK.init_shadow_repo(base)
        (base / "a.txt").write_text("v1\n", encoding="utf-8")
        sha_v1, _ = CK.snapshot(base, "v1")
        assert sha_v1
        (base / "a.txt").write_text("v2\n", encoding="utf-8")
        (base / "added-later.txt").write_text("only in v2\n", encoding="utf-8")
        sha_v2, _ = CK.snapshot(base, "v2")
        assert sha_v2

        # Restore to v1
        ok, msg = CK.restore(base, sha_v1)
        assert ok, f"restore failed: {msg}"
        # File rolled back
        assert (base / "a.txt").read_text(encoding="utf-8") == "v1\n"
        # Untracked-in-v1 file should be gone
        assert not (base / "added-later.txt").exists(), \
            "restore should have removed added-later.txt"
        # We can still see sha_v2 in `git log`
        rows = CK.list_checkpoints(base, limit=10)
        # After restore HEAD now points at sha_v1, but sha_v2 commit
        # still exists in the object store -- git log walks back from
        # HEAD though, so v2 is no longer listed via log. That's the
        # expected git-style behavior. We confirm HEAD moved:
        assert rows[0]["sha"] == sha_v1
        # Still resolvable directly by sha
        assert CK.resolve_ref(base, sha_v2) == sha_v2
        print("[PASS] restore round-trip (file rolled back; new file removed)")


# ===========================================================================
# Test 4: .open-code/ is excluded from snapshots
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    if not _skip_if_no_git("exclude .open-code/"):
        CK.init_shadow_repo(base)
        (base / "a.txt").write_text("hello\n", encoding="utf-8")
        # Touch some files inside .open-code/ that must NOT be snapshotted
        (base / ".open-code").mkdir(exist_ok=True)
        (base / ".open-code" / "secret.txt").write_text("PRIVATE\n",
                                                         encoding="utf-8")
        sha, _ = CK.snapshot(base, "exclude test")
        assert sha
        # Inspect what's in the tree at HEAD
        import subprocess
        sd = base / ".open-code" / "checkpoints.git"
        cp = subprocess.run(
            ["git", f"--git-dir={sd}", f"--work-tree={base}",
             "ls-tree", "-r", "--name-only", "HEAD"],
            cwd=str(base), capture_output=True, text=True, check=True,
        )
        tracked = cp.stdout.splitlines()
        assert "a.txt" in tracked, f"a.txt missing from tracked list: {tracked}"
        for t in tracked:
            assert not t.startswith(".open-code/"), \
                f"shadow repo leaked .open-code/ contents: {t}"
        print("[PASS] .open-code/ excluded from snapshots")


# ===========================================================================
# Test 5: append_checkpoint event semantics
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    store_root = Path(d).resolve()
    store = SX.SessionStore(store_root)
    s = store.create("/tmp/x", "fake-model", "test ckpt event")
    store.append_checkpoint(s, sha="a" * 40, label="turn-start: rename foo",
                             phase="turn-start")
    store.append_checkpoint(s, sha="b" * 40, label="manual",
                             phase="manual")
    # Read events back from JSONL
    import json
    events = []
    with s.path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    ckpts = [e for e in events if e.get("kind") == "checkpoint"]
    assert len(ckpts) == 2
    assert ckpts[0]["sha"] == "a" * 40
    assert ckpts[0]["short_sha"] == "a" * 10
    assert ckpts[0]["phase"] == "turn-start"
    assert ckpts[0]["label"] == "turn-start: rename foo"
    assert ckpts[1]["phase"] == "manual"
print("[PASS] append_checkpoint events recorded in JSONL")


# ===========================================================================
# Test 6: snapshot graceful when git is missing -- covered by Test code
# itself if _HAVE_GIT is False. Otherwise: simulate by forcing
# CK._git_available to return False.
# ===========================================================================
orig = CK._git_available
try:
    CK._git_available = lambda: False
    with tempfile.TemporaryDirectory() as d:
        base = Path(d).resolve()
        sha, msg = CK.snapshot(base, "should fail")
        assert sha is None
        assert "git" in msg.lower()
        print("[PASS] snapshot returns (None, msg) when git unavailable")
finally:
    CK._git_available = orig


print("\nOK -- checkpoints probes passed.")
