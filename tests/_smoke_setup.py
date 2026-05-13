"""Common setup for `_live_*_check.py` scripts.

Reconfigures `sys.stdout` / `sys.stderr` to UTF-8 with
`errors='replace'` so model output containing emoji, fractions
(e.g. gpt-5-mini's ?), em-dashes etc. doesn't crash on Windows
cp1252-redirected consoles. Mirrors the preamble that
`open_code.py` runs at import.

Import as the first non-stdlib line in each smoke:

    import sys; sys.path.insert(0, str(...))  # open-code root
    import _smoke_setup  # noqa: F401  -- side-effect import
"""
import sys

for _s in ("stdout", "stderr"):
    _st = getattr(sys, _s, None)
    if _st is not None and hasattr(_st, "reconfigure"):
        try:
            _st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
