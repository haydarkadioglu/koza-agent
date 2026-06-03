## Coding Philosophy
- Write clean, working code — no disclaimers, no skeletons.
- **Before installing any package**, check with `python -c "import pkg"` or `pip show pkg`.
- Prefer the most direct solution; avoid over-engineering.
- If a library is missing, resolve it autonomously: check the current Python executable, try the project venv, then user/site install, then a temporary venv if system package policy blocks global pip.
- Do not ask "continue?" after dependency failures. Try the next safe install/import path and verify with an import check.
- For PDFs use the installed `pypdf` package first (`from pypdf import PdfReader`). Use `PyPDF2` only as a fallback if it is already installed.
