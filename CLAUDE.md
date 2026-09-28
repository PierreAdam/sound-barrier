# Sound-Barrier

Subsonic-compatible music server. Architecture and roadmap: `ARCHITECTURE.md`.
Backend setup and commands: `backend/README.md`.

Start everything for manual testing: `./dev.sh` (Git Bash on Windows), stop Postgres with `./dev.sh down`.

## Python environment

- Always use the virtualenv at `backend/.venv` (Windows: `backend/.venv/Scripts/…`).
  Never install packages globally or use the system `python` to run project code.
- Install / refresh: `backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt`.
- When adding a dependency: add it to `backend/pyproject.toml`, install it in the venv, then
  regenerate `requirements.txt` / `requirements-dev.txt` (see `backend/README.md`, "Dependencies").

## Before finishing a change (from `backend/`)

```bash
.venv/Scripts/ruff format . && .venv/Scripts/ruff check --fix .
.venv/Scripts/pyright
.venv/Scripts/pytest            # needs Docker running (Postgres via Testcontainers)
```

## Frontend (`frontend/`, React + Vite + TypeScript)

```bash
npm run typecheck && npm test && npm run build
```

- All styles go in `frontend/src/theme/theme.less` (tokens at the top); components use class names only.
- Colors are CSS custom properties (palettes at the top of `theme.less`, switched by
  `data-theme` / `data-accent` on `<html>`): use `color-mix()`, not Less color functions.
  A new accent goes in `theme.less` (`.accent-palette`) and in `src/theme/appearance.ts`.
- The web UI calls the Subsonic API (`/rest`) through `src/api/subsonic.ts`. Our own future
  endpoints live under `/api` with a separate client; never mix them.
- Dev servers: `.claude/launch.json` (`backend` on 4040, `frontend` on 5173 with a proxy).

## Conventions

- Business logic lives in `app/services/`; `app/subsonic/` only adapts the wire format.
- The scanner (`app/scanner/`) is the only writer of library tables.
- Schema changes go through Alembic migrations (`alembic revision --autogenerate`).
- Line endings: LF (enforced by ruff format).
