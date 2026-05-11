"""Probe: managed (enterprise) settings enforcement (Tier 2 #25).

Verifies:
  - OPEN_CODE_MANAGED_SETTINGS_TEST env var override is honored
  - Managed settings override user/project/local
  - Managed deny rules union with project deny rules (defense-in-depth)
  - When no managed file exists, behavior matches pre-#25
  - Managed `hooks.disabled=True` overrides user `hooks.disabled=False`
"""
from __future__ import annotations
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import settings as S


# ===========================================================================
# Test 1: managed settings override conflicting user/project values
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    # Project says: model=A, hooks.disabled=False
    proj = base / ".open-code"
    proj.mkdir()
    (proj / "settings.json").write_text(json.dumps({
        "model": "project-model",
        "hooks": {"disabled": False},
    }), encoding="utf-8")
    # Managed says: model=ENFORCED, hooks.disabled=True
    mp = base / "managed.json"
    mp.write_text(json.dumps({
        "model": "managed-model",
        "hooks": {"disabled": True},
    }), encoding="utf-8")
    os.environ["OPEN_CODE_MANAGED_SETTINGS_TEST"] = str(mp)
    try:
        s = S.load_layered_settings(base)
    finally:
        os.environ.pop("OPEN_CODE_MANAGED_SETTINGS_TEST", None)
    assert s.model == "managed-model", f"managed should override: got {s.model}"
    assert s.hooks_disabled is True, "managed hooks.disabled should win"
    assert mp in s.sources, f"managed path should appear in sources: {s.sources}"
print("[PASS] managed settings override user/project model + hooks.disabled")


# ===========================================================================
# Test 2: managed deny rules UNION with project deny rules
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    proj = base / ".open-code"
    proj.mkdir()
    (proj / "settings.json").write_text(json.dumps({
        "permissions": {"deny": ["run_shell(rm *)"]},
    }), encoding="utf-8")
    mp = base / "managed.json"
    mp.write_text(json.dumps({
        "permissions": {"deny": ["run_shell(sudo *)"]},
    }), encoding="utf-8")
    os.environ["OPEN_CODE_MANAGED_SETTINGS_TEST"] = str(mp)
    try:
        s = S.load_layered_settings(base)
    finally:
        os.environ.pop("OPEN_CODE_MANAGED_SETTINGS_TEST", None)
    deny = s.permissions.deny
    assert "run_shell(rm *)" in deny, f"project deny missing from {deny}"
    assert "run_shell(sudo *)" in deny, f"managed deny missing from {deny}"
print("[PASS] managed deny rules union with project deny rules")


# ===========================================================================
# Test 3: when no managed file exists, behavior is unchanged
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    proj = base / ".open-code"
    proj.mkdir()
    (proj / "settings.json").write_text(json.dumps({
        "model": "project-only",
    }), encoding="utf-8")
    # Point env at a non-existent file
    nonexistent = base / "does-not-exist.json"
    os.environ["OPEN_CODE_MANAGED_SETTINGS_TEST"] = str(nonexistent)
    try:
        s = S.load_layered_settings(base)
    finally:
        os.environ.pop("OPEN_CODE_MANAGED_SETTINGS_TEST", None)
    assert s.model == "project-only"
    assert nonexistent not in s.sources, \
        "non-existent managed path should NOT appear in sources"
print("[PASS] non-existent managed path is a silent no-op")


# ===========================================================================
# Test 4: managed allow tier (always_allow) does NOT bypass managed deny
# ===========================================================================
# Even an admin's managed "always_allow" must not weaken a managed
# "deny". Defense-in-depth.
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    mp = base / "managed.json"
    mp.write_text(json.dumps({
        "permissions": {
            "deny": ["run_shell"],
            "always_allow": ["run_shell"],
        },
    }), encoding="utf-8")
    os.environ["OPEN_CODE_MANAGED_SETTINGS_TEST"] = str(mp)
    try:
        s = S.load_layered_settings(base)
    finally:
        os.environ.pop("OPEN_CODE_MANAGED_SETTINGS_TEST", None)
    decision, why = S.evaluate_permission(
        "run_shell", {"command": "ls"}, s.permissions,
    )
    assert decision == "deny", f"deny must beat always_allow; got {decision}: {why}"
print("[PASS] deny still beats always_allow at the managed layer")


# ===========================================================================
# Test 5: multiple managed paths layered last-wins (env supports list)
# ===========================================================================
sep = ";" if os.name == "nt" else ":"
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    proj = base / ".open-code"
    proj.mkdir()
    (proj / "settings.json").write_text(json.dumps({
        "model": "project-model",
    }), encoding="utf-8")
    m1 = base / "m1.json"
    m1.write_text(json.dumps({"model": "managed-1"}), encoding="utf-8")
    m2 = base / "m2.json"
    m2.write_text(json.dumps({"model": "managed-2"}), encoding="utf-8")
    os.environ["OPEN_CODE_MANAGED_SETTINGS_TEST"] = f"{m1}{sep}{m2}"
    try:
        s = S.load_layered_settings(base)
    finally:
        os.environ.pop("OPEN_CODE_MANAGED_SETTINGS_TEST", None)
    # m2 listed second, so its `model` wins
    assert s.model == "managed-2", f"expected managed-2; got {s.model}"
print("[PASS] multiple managed paths layered last-wins")


print("\nOK -- managed-settings probes passed.")
