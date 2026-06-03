## Shell & Command Execution
- On Windows use PowerShell; on Linux/macOS use bash.
- Chain commands with `&&` / `;` when possible.
- If a CLI tool or Python module is missing, diagnose and fix without asking: check PATH/version, install in the active project/venv when possible, or write a small Python fallback.
- If system-managed Python blocks pip, do not stop. Use the existing project venv, `python -m venv`, `pipx`, or OS package manager as appropriate, then verify the command/import.
- Keep shell progress terse. Report only the failing command, the next fix, and final result.
