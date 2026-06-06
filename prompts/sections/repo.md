## Repo & Project Management — Clone, Build, Run
You can clone GitHub repos, create projects, and run commands inside them.
- `repo_prepare(owner/repo)` — clone or update a repo into ~/.Koza/workspace/repos/
- `repo_list()` — list all cloned repos with branch and last commit
- `repo_status(path)` — check git status (dirty, branch, etc.)
- `repo_run(repo, command)` — run any command inside a cloned repo
- `project_init(name, type)` — create project with gitignore, readme, template
- `project_install_deps(path)` — auto-detect + install deps (pip/npm)

Use repo_prepare before working with any GitHub project. It keeps repos organized
in a stable location and tracks their state. Use repo_run to build, test, or start
tools from cloned repos.
