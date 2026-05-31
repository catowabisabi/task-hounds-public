# Quick Start

This guide starts Task Hounds locally for development.

## Requirements

- Python 3.11+
- Node.js 20+
- npm
- OpenCode CLI on `PATH`

## Install

```bash
git clone https://github.com/catowabisabi/task-hounds.git
cd task-hounds
pip install -r requirements.txt
pip install .
```

Build the dashboard:

```bash
cd ui/web
npm ci
npm run build
cd ../..
```

## Run

```bash
PYTHONPATH=core python core/api/server.py --port 8765
```

Windows PowerShell:

```powershell
$env:PYTHONPATH = "core"
python core\api\server.py --port 8765
```

Open http://localhost:8765.

## Start an Agent Loop

1. Create or select a workspace.
2. Write a Human Directive.
3. Press Start Loop or Run Once.

Task Hounds will not start autonomous work without a pending Human Directive.

## Logs

Runtime logs are local-only and ignored by git:

```bash
tail -f core/runtime/logs/runner.log
```

Agent streams are stored under the active runtime session in `core/runtime/`.
