"""Probe: sticky session permissions (Tier 2 #17).

The "ask" interactive prompt now offers four choices:
  y -> allow once
  s -> sticky-session (allow this tool until /clear / new REPL session)
  a -> always (persist allow-rule to .open-code/settings.local.json)
  n -> deny

Tests:
  1. _persist_sticky_rule writes a valid rule that load_layered_settings
     reads back as an allow-rule.
  2. _persist_sticky_rule appends to an existing allow list without
     clobbering other rules.
  3. _persist_sticky_rule refuses to overwrite a malformed JSON file.
  4. The sticky-session path: a tool listed in settings._sticky_allow
     resolves to "allow" without going through the interactive prompt.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import open_code as OC
import settings as S


# ===========================================================================
# Test 1: _persist_sticky_rule writes a working allow rule
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    cwd = Path(d).resolve()
    OC._persist_sticky_rule(cwd, "run_shell")
    settings_file = cwd / ".open-code" / "settings.local.json"
    assert settings_file.exists()
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    # Tier 2 #17: rule goes to always_allow so it wins over ask
    assert data["permissions"]["always_allow"] == ["run_shell"]
    # load_layered_settings should read it back
    merged = S.load_layered_settings(cwd)
    assert "run_shell" in merged.permissions.always_allow
    # Critical: always_allow overrides a competing ask rule
    perm = S.PermissionRules(
        ask=["run_shell"], always_allow=list(merged.permissions.always_allow),
    )
    decision, why = S.evaluate_permission(
        "run_shell", {"command": "ls"}, perm,
    )
    assert decision == "allow", f"always_allow should beat ask; got {decision}: {why}"
    assert "always_allow" in why
print("[PASS] always_allow overrides competing ask rule after _persist_sticky_rule")


# ===========================================================================
# Test 2: appending to existing rules preserves them
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    cwd = Path(d).resolve()
    settings_dir = cwd / ".open-code"
    settings_dir.mkdir()
    prior = {
        "model": "gemini-3.1-flash-lite-preview",
        "permissions": {
            "deny": ["run_shell(rm -rf *)"],
            "allow": ["read_file"],
        },
        "statusLine": {"enabled": True},
    }
    (settings_dir / "settings.local.json").write_text(
        json.dumps(prior, indent=2), encoding="utf-8",
    )
    OC._persist_sticky_rule(cwd, "run_shell")
    data = json.loads(
        (settings_dir / "settings.local.json").read_text(encoding="utf-8"),
    )
    # Pre-existing keys preserved
    assert data["model"] == "gemini-3.1-flash-lite-preview"
    assert data["statusLine"] == {"enabled": True}
    assert data["permissions"]["deny"] == ["run_shell(rm -rf *)"]
    # New rule appended to always_allow, old allow list kept untouched
    assert "run_shell" in data["permissions"]["always_allow"]
    assert "read_file" in data["permissions"]["allow"]
    # Idempotent (no duplicates)
    OC._persist_sticky_rule(cwd, "run_shell")
    data2 = json.loads(
        (settings_dir / "settings.local.json").read_text(encoding="utf-8"),
    )
    assert data2["permissions"]["always_allow"].count("run_shell") == 1
print("[PASS] _persist_sticky_rule preserves other settings & is idempotent")


# ===========================================================================
# Test 3: refuses to clobber malformed JSON
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    cwd = Path(d).resolve()
    settings_dir = cwd / ".open-code"
    settings_dir.mkdir()
    (settings_dir / "settings.local.json").write_text(
        "this is not valid json {", encoding="utf-8",
    )
    raised = False
    try:
        OC._persist_sticky_rule(cwd, "run_shell")
    except RuntimeError as exc:
        raised = True
        assert "valid JSON" in str(exc)
    assert raised, "expected RuntimeError on malformed settings.local.json"
print("[PASS] _persist_sticky_rule refuses to overwrite malformed JSON")


# ===========================================================================
# Test 4: sticky-session bypass in run_loop's permission gate
# ===========================================================================
# We don't exercise the interactive prompt itself (no tty). Instead we
# pre-set settings._sticky_allow = {"run_shell"} and verify the gate
# resolves "ask" -> "allow" without prompting.
import tempfile, shutil
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    import sessions as SX
    store = SX.SessionStore(base / "store")
    (base / "store").mkdir(parents=True, exist_ok=True)
    s = store.create(str(base), "fake", "sticky test")

    st = S.Settings()
    st.permissions = S.PermissionRules(ask=["run_shell"])
    st._sticky_allow = {"run_shell"}  # type: ignore[attr-defined]

    # We patch the input() function to ensure it is NEVER called.
    # If sticky-session works, the gate resolves to allow without
    # prompting. We also patch tools.TOOL_FUNCTIONS["run_shell"] to a
    # stub that returns ok=True so the loop terminates fast.
    import tools as _tools
    orig_run = _tools.TOOL_FUNCTIONS.get("run_shell")
    _tools.TOOL_FUNCTIONS["run_shell"] = lambda **kw: {
        "ok": True, "stdout": "stub", "exit_code": 0,
    }

    # Stub Gemini client: turn 1 makes a run_shell call; turn 2 stops.
    from google.genai import types as _t
    call_count = {"n": 0}

    class _Resp1:
        usage_metadata = None
        def __init__(self):
            self.candidates = [type("C", (), {
                "content": _t.Content(
                    role="model",
                    parts=[_t.Part.from_function_call(
                        name="run_shell",
                        args={"command": "echo hi"},
                    )],
                )
            })()]

    class _Resp2:
        usage_metadata = None
        def __init__(self):
            self.candidates = [type("C", (), {
                "content": _t.Content(
                    role="model",
                    parts=[_t.Part.from_text(text="done")],
                )
            })()]

    class _StubModels:
        def generate_content(self, **kwargs):
            call_count["n"] += 1
            return _Resp2() if call_count["n"] >= 2 else _Resp1()
        def generate_content_stream(self, **kwargs):
            return iter([])

    class _StubClient:
        def __init__(self, **kwargs):
            self.models = _StubModels()

    prior_cwd = OC.CONFIG.cwd
    OC.CONFIG.cwd = base
    try:
        # Critical: if sticky bypass works, input() should NEVER be called.
        def _no_prompt(*args, **kwargs):
            raise AssertionError(
                "input() was called — sticky-session bypass failed"
            )
        with patch("open_code.genai.Client", _StubClient), \
             patch("builtins.input", _no_prompt):
            exit_code, metrics = OC.run_loop(
                task="run echo", model="fake", api_key="x",
                max_iterations=4, store=store, session=s,
                verbose=False, stream=False,
                fire_session_start=False,
                settings=st, is_repl=True,  # CRUCIAL: is_repl=True
                                            # so the ask path is reachable
            )
        assert exit_code == 0
        assert metrics["tool_calls"] >= 1
        assert metrics["tool_errors"] == 0, \
            f"expected zero tool errors with sticky bypass; got {metrics['tool_errors']}"
    finally:
        OC.CONFIG.cwd = prior_cwd
        if orig_run is not None:
            _tools.TOOL_FUNCTIONS["run_shell"] = orig_run

print("[PASS] sticky-session bypass skips interactive prompt for whitelisted tool")


print("\nOK -- sticky-permissions probes passed.")
