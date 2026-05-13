"""Quick smoke: PowerShell tool wiring."""
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import _smoke_setup  # noqa: F401  -- UTF-8 stdout/stderr on Windows

os.environ["OPEN_CODE_USE_POWERSHELL"] = "1"
import tools

# Use a command that exercises PowerShell-specific syntax cmd.exe can't run.
r = tools.tool_run_shell('Write-Output "hello from pwsh"; Get-Date -Format yyyy-MM-dd')
print("ok:", r["ok"], "exit:", r["exit_code"], flush=True)
print("---stdout---", flush=True)
print(r["stdout"], flush=True)
print("---stderr---", flush=True)
print(r["stderr"], flush=True)

# Negative test: without the env var, the same syntax should fail under cmd
del os.environ["OPEN_CODE_USE_POWERSHELL"]
r2 = tools.tool_run_shell('Write-Output "hello"')
print("---cmd path---", flush=True)
print("ok:", r2["ok"], "exit:", r2["exit_code"], flush=True)
print("stderr:", (r2.get("stderr") or "")[:200], flush=True)
