# Task Hounds API Server

This directory contains the Python HTTP API server for Task Hounds.

The web UI is served from `ui/web/dist/`. Build it first:

```powershell
cd ui/web
npm ci
npm run build
cd ../..
```

Start the server from the project root:

```powershell
$env:PYTHONPATH = "core"
python core/api/server.py --port 8765
```

Then open http://localhost:8765.

## Key Paths

- API server: `core/api/server.py`
- SQLite schema: `core/db/schema.sql`
- Runtime files: `core/runtime/`
- Web build output: `ui/web/dist/`

Runtime data, local databases, logs, and OpenCode config are intentionally ignored by git.
