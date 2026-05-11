"""Adversarial path-sandbox probes for v0.2.0 brutal review."""
from __future__ import annotations
import os, sys, tempfile, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import CONFIG, tool_write_file

# ---- 1) Symlink escape ----
print("=== Symlink escape ===")
sb = Path(tempfile.mkdtemp(prefix="ocsym-"))
out = Path(tempfile.mkdtemp(prefix="ocout-"))
CONFIG.cwd = sb
CONFIG.allow_outside_cwd = False
try:
    link = sb / "inside-link"
    try:
        os.symlink(str(out), str(link), target_is_directory=True)
        sym_ok = True
    except OSError as e:
        sym_ok = False
        print(f"  (symlink unsupported: {e})")
    if sym_ok:
        r = tool_write_file(str(link / "pwned.txt"), "gotcha")
        target = out / "pwned.txt"
        print(f"  Result: ok={r.get('ok')} err={r.get('error','-')[:80]}")
        print(f"  Escape file written outside CWD: {target.exists()}")
        if target.exists():
            print("  >>> SYMLINK ESCAPE WORKED — sandbox bypass")
finally:
    shutil.rmtree(sb, ignore_errors=True)
    shutil.rmtree(out, ignore_errors=True)

# ---- 2) Tilde expansion bypass ----
print("\n=== Tilde expansion ===")
sb = Path(tempfile.mkdtemp(prefix="octilde-"))
CONFIG.cwd = sb
CONFIG.allow_outside_cwd = False
try:
    target = Path.home() / "_oc_tilde_escape_probe.txt"
    if target.exists():
        target.unlink()
    r = tool_write_file("~/_oc_tilde_escape_probe.txt", "via tilde")
    print(f"  Result: ok={r.get('ok')} err={(r.get('error') or '-')[:80]}")
    print(f"  Tilde escape file exists at {target}: {target.exists()}")
    if target.exists():
        print("  >>> TILDE ESCAPE WORKED")
        target.unlink()
finally:
    shutil.rmtree(sb, ignore_errors=True)

# ---- 3) Case-insensitive Windows path edge ----
print("\n=== Windows case-mixed CWD ===")
sb = Path(tempfile.mkdtemp(prefix="OCcase-"))
CONFIG.cwd = sb
CONFIG.allow_outside_cwd = False
# Try to write to a path that differs only by case
mixed = str(sb).swapcase()
try:
    r = tool_write_file(mixed + "\\probe.txt", "case test")
    print(f"  Mixed-case write result: ok={r.get('ok')} err={(r.get('error') or '-')[:120]}")
finally:
    shutil.rmtree(sb, ignore_errors=True)

# ---- 4) UNC path ----
print("\n=== UNC path ===")
sb = Path(tempfile.mkdtemp(prefix="ocunc-"))
CONFIG.cwd = sb
CONFIG.allow_outside_cwd = False
try:
    r = tool_write_file(r"\\127.0.0.1\C$\Temp\unc.txt", "unc test")
    print(f"  UNC write result: ok={r.get('ok')} err={(r.get('error') or '-')[:120]}")
finally:
    shutil.rmtree(sb, ignore_errors=True)
