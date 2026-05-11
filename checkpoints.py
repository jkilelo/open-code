"""Shadow-git checkpoints (Tier 2 #11).

A side git repository at `.open-code/checkpoints.git/` that snapshots
the workspace independently of the user's real `.git`. Lets the model
make changes and lets the user `/restore` to any prior point without
polluting their commit history.

Design notes:
- Bare git dir lives at `.open-code/checkpoints.git/` (NOT a normal
  repo with worktree). All commands pass `--git-dir=<that path>` plus
  `--work-tree=<cwd>` so the working tree is just the user's project.
- The shadow repo's `info/exclude` excludes `.open-code/` and `.git/`
  so we never snapshot our own state or the user's real git.
- `snapshot()` is best-effort: if `git` isn't installed, it returns
  None and the caller treats checkpointing as unavailable.
- `restore()` is destructive: it does a `checkout-index --force --all`
  + a `clean -fd` (excluding our excludes). The caller MUST confirm
  with the user first; this module does not prompt.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SHADOW_DIR_REL = ".open-code/checkpoints.git"
EXCLUDE_LINES = [
    ".open-code/",
    ".git/",
    "node_modules/",
    "__pycache__/",
    "*.pyc",
    ".venv/",
    "venv/",
    ".tox/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "dist/",
    "build/",
    "*.egg-info/",
]
_GIT_BIN = "git"


def _git_available() -> bool:
    return shutil.which(_GIT_BIN) is not None


def shadow_dir(cwd: Path) -> Path:
    return cwd / SHADOW_DIR_REL


def is_initialized(cwd: Path) -> bool:
    sd = shadow_dir(cwd)
    return sd.exists() and (sd / "HEAD").exists()


def _git(cwd: Path, *args: str, check: bool = True,
         timeout: float = 30.0) -> "subprocess.CompletedProcess[str]":
    sd = shadow_dir(cwd)
    cmd = [_GIT_BIN, f"--git-dir={sd}", f"--work-tree={cwd}", *args]
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True,
        check=check, timeout=timeout,
    )


def init_shadow_repo(cwd: Path) -> tuple[bool, str]:
    """Initialize the shadow git dir if not already present.

    Returns (ok, message). Idempotent.
    """
    if not _git_available():
        return (False, "git binary not found on PATH; checkpoints unavailable")
    sd = shadow_dir(cwd)
    if is_initialized(cwd):
        return (True, f"already initialized at {sd}")
    sd.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [_GIT_BIN, "init", "--bare", "--quiet", str(sd)],
            check=True, capture_output=True, text=True, timeout=20.0,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return (False, f"git init failed: {exc}")
    # Write exclude file so we don't snapshot our own state.
    info_dir = sd / "info"
    info_dir.mkdir(parents=True, exist_ok=True)
    (info_dir / "exclude").write_text(
        "\n".join(EXCLUDE_LINES) + "\n", encoding="utf-8",
    )
    # Configure a local user so commits don't fail on machines that
    # have no global git identity.
    try:
        _git(cwd, "config", "user.name", "open-code-shadow", timeout=10.0)
        _git(cwd, "config", "user.email", "shadow@open-code.local",
             timeout=10.0)
        # Speed: avoid GPG-signing if user has it globally on.
        _git(cwd, "config", "commit.gpgsign", "false", timeout=10.0)
    except subprocess.CalledProcessError:
        pass  # nice-to-have; not fatal
    return (True, f"initialized shadow repo at {sd}")


def snapshot(cwd: Path, label: str, *,
             auto_init: bool = True) -> tuple[str | None, str]:
    """Take a snapshot of the current working tree.

    Returns (commit_sha_or_None, message). On failure (no git binary,
    git error, nothing to commit on first run-with-no-changes), the
    sha is None and the message explains why.
    """
    if not _git_available():
        return (None, "git not available")
    if not is_initialized(cwd):
        if not auto_init:
            return (None, "shadow repo not initialized")
        ok, msg = init_shadow_repo(cwd)
        if not ok:
            return (None, f"auto-init failed: {msg}")
    try:
        _git(cwd, "add", "-A", timeout=60.0)
        # Use commit --allow-empty so we always get a sha even if the
        # working tree is unchanged. This is critical: the model may
        # be about to start work, and we want a marker even if the
        # state is identical to the last snapshot.
        label_safe = (label or "(no label)").replace("\n", " ").strip()[:200]
        if not label_safe:
            label_safe = "(no label)"
        _git(cwd, "commit", "--allow-empty", "-m", label_safe,
             timeout=60.0)
        rev = _git(cwd, "rev-parse", "HEAD", timeout=10.0)
        sha = (rev.stdout or "").strip()
        if not sha:
            return (None, "rev-parse returned empty sha")
        return (sha, f"snapshot {sha[:10]} — {label_safe}")
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or "").strip()[:300]
        return (None, f"git error: {err}")
    except subprocess.TimeoutExpired:
        return (None, "git command timed out")


def list_checkpoints(cwd: Path, limit: int = 20) -> list[dict[str, str]]:
    """Return a list of recent checkpoint dicts (newest first).

    Each dict: {"sha", "short_sha", "label", "ts"} where ts is the
    committer date in ISO-8601.
    """
    if not is_initialized(cwd):
        return []
    try:
        fmt = "%H%x09%cI%x09%s"
        cp = _git(cwd, "log", f"--max-count={int(limit)}", f"--pretty={fmt}",
                  timeout=15.0)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    out: list[dict[str, str]] = []
    for line in (cp.stdout or "").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        sha, ts, label = parts[0], parts[1], parts[2]
        out.append({
            "sha": sha, "short_sha": sha[:10],
            "ts": ts, "label": label,
        })
    return out


def resolve_ref(cwd: Path, ref: str) -> str | None:
    """Resolve a short sha / branch / HEAD~N to a full sha. Returns
    None on failure."""
    if not is_initialized(cwd):
        return None
    try:
        cp = _git(cwd, "rev-parse", "--verify", ref, timeout=10.0)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    sha = (cp.stdout or "").strip()
    return sha or None


def diff_summary(cwd: Path, ref_from: str, ref_to: str = "HEAD") -> str:
    """Return `git diff --stat ref_from..ref_to` for a preview."""
    if not is_initialized(cwd):
        return "(shadow repo not initialized)"
    try:
        cp = _git(cwd, "diff", "--stat", f"{ref_from}..{ref_to}",
                  check=False, timeout=15.0)
    except subprocess.TimeoutExpired:
        return "(diff timed out)"
    return (cp.stdout or cp.stderr or "(no diff output)").strip() or "(no changes)"


def restore(cwd: Path, ref: str) -> tuple[bool, str]:
    """Restore the working tree to the given checkpoint ref.

    Strategy:
      1. Resolve ref -> sha.
      2. `read-tree --reset -u <sha>` to update the index + worktree.
      3. `clean -fd` (honors info/exclude) to wipe new files that
         weren't in the snapshot.
      4. Update HEAD so subsequent snapshots branch from this point.

    DOES NOT prompt the user. Caller MUST confirm first.
    """
    if not _git_available():
        return (False, "git not available")
    if not is_initialized(cwd):
        return (False, "shadow repo not initialized")
    sha = resolve_ref(cwd, ref)
    if sha is None:
        return (False, f"unknown ref {ref!r}")
    try:
        _git(cwd, "read-tree", "--reset", "-u", sha, timeout=60.0)
        # `clean -fd` wipes files/dirs untracked by THIS index. The
        # info/exclude file keeps `.open-code/` and `.git/` safe.
        _git(cwd, "clean", "-fd", timeout=60.0)
        # Move shadow HEAD to the restored sha so future snapshots
        # are based on it.
        _git(cwd, "update-ref", "HEAD", sha, timeout=10.0)
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or "").strip()[:300]
        return (False, f"restore failed: {err}")
    except subprocess.TimeoutExpired:
        return (False, "restore timed out")
    return (True, f"restored to {sha[:10]}")
