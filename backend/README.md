# Sound-Barrier backend

Subsonic-compatible music server (FastAPI + PostgreSQL). See [../ARCHITECTURE.md](../ARCHITECTURE.md).

## Setup

All Python commands use the virtualenv in `backend/.venv`.
On Linux/macOS, replace `.venv/Scripts/` with `.venv/bin/`.

```bash
# from the repository root: start Postgres
docker compose up -d postgres

# from backend/
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
cp .env.example .env                               # then set SOUND_BARRIER_SECRET_KEY:
.venv/Scripts/sound-barrier gen-secret

.venv/Scripts/alembic upgrade head
.venv/Scripts/sound-barrier add-folder Music /path/to/music
.venv/Scripts/sound-barrier serve                  # http://localhost:4040/rest/...
```

On first start, the server creates the user **`admin` / `admin`** (only when there is no
user at all). Change its password right away:

```bash
.venv/Scripts/sound-barrier set-password admin
```

The server logs a warning at every start while the default password is still in use.

## Commands

| Command | Purpose |
|---|---|
| `sound-barrier gen-secret` | New key for `SOUND_BARRIER_SECRET_KEY` (encrypts passwords; keep it safe) |
| `sound-barrier serve [--port 4040] [--reload]` | Run the server |
| `sound-barrier create-user NAME [--admin] [--email E]` | Create a user (prompts for password) |
| `sound-barrier set-password NAME` | Change a password |
| `sound-barrier create-api-key NAME LABEL` | OpenSubsonic API key (shown once) |
| `sound-barrier add-folder NAME PATH` / `list-folders` | Manage library roots |
| `sound-barrier scan [--full]` | Scan the library now (quick: changed files only) |

## Dependencies

- `pyproject.toml` declares the direct dependencies (version ranges).
- `requirements.txt` pins the full runtime set; `requirements-dev.txt` adds test/lint
  tools and installs the project in editable mode.

After changing dependencies in `pyproject.toml`, regenerate the pinned files:

```bash
# runtime set, from a clean temporary venv
python -m venv /tmp/rt && /tmp/rt/bin/pip install . && /tmp/rt/bin/pip freeze --exclude sound-barrier
# full dev set, from backend/.venv
.venv/Scripts/python -m pip install -e ".[dev]" && .venv/Scripts/python -m pip freeze --exclude-editable
```

Keep Windows-only packages (`pywin32`, `colorama`) marked with `; sys_platform == "win32"`,
and Linux-only ones (`uvloop`, used in the Docker image) with `; sys_platform != "win32"`.

## Development

```bash
.venv/Scripts/pytest            # unit + integration (integration needs Docker running)
.venv/Scripts/pytest tests/unit # unit tests only
.venv/Scripts/ruff check --fix . && .venv/Scripts/ruff format .
.venv/Scripts/pyright
.venv/Scripts/alembic revision --autogenerate -m "describe change"
```
