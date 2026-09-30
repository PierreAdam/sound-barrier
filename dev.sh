#!/usr/bin/env bash
# Starts the whole stack for local testing: Postgres (Docker), backend, frontend.
#
#   ./dev.sh          set up what is missing, then run everything (Ctrl+C to stop)
#   ./dev.sh down     stop the Postgres container
#
# Works in Git Bash on Windows, and on Linux/macOS.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
BACKEND_PORT=4040
FRONTEND_PORT=5173

case "$(uname -s)" in
  MINGW* | MSYS* | CYGWIN*) WINDOWS=1; VENV_BIN="$BACKEND/.venv/Scripts" ;;
  *) WINDOWS=0; VENV_BIN="$BACKEND/.venv/bin" ;;
esac

if [ -t 1 ]; then
  BOLD=$'\e[1m' DIM=$'\e[2m' RED=$'\e[31m' GREEN=$'\e[32m' YELLOW=$'\e[33m' BLUE=$'\e[34m' MAGENTA=$'\e[35m' RESET=$'\e[0m'
else
  BOLD="" DIM="" RED="" GREEN="" YELLOW="" BLUE="" MAGENTA="" RESET=""
fi

step() { echo "${BOLD}${BLUE}==>${RESET} ${BOLD}$*${RESET}"; }
info() { echo "    ${DIM}$*${RESET}"; }
warn() { echo "${YELLOW}warning:${RESET} $*"; }
die() { echo "${RED}error:${RESET} $*" >&2; exit 1; }

# Hash of a file, to reinstall dependencies only when their lock file changed.
file_hash() { sha1sum "$1" | cut -d' ' -f1; }

port_in_use() {
  if [ "$WINDOWS" = 1 ]; then
    netstat -ano 2>/dev/null | grep -Eq "[:.]$1[[:space:]].*LISTENING"
  else
    (echo >/dev/tcp/127.0.0.1/"$1") >/dev/null 2>&1
  fi
}

# --- down -------------------------------------------------------------------

if [ "${1:-}" = "down" ]; then
  step "Stopping Postgres"
  docker compose -f "$ROOT/docker/docker-compose.dev.yml" stop postgres
  exit 0
elif [ -n "${1:-}" ]; then
  die "unknown command: $1 (usage: ./dev.sh [down])"
fi

# --- prerequisites ------------------------------------------------------------

step "Checking prerequisites"
command -v docker >/dev/null || die "Docker is not installed (https://www.docker.com/products/docker-desktop/)"
command -v node >/dev/null || die "Node.js is not installed (https://nodejs.org/)"
command -v npm >/dev/null || die "npm is not installed"
# First interpreter that really runs and is recent enough. On Windows, `python3` is often
# a Microsoft Store placeholder that only prints a message.
PYTHON=""
for candidate in python3 python py; do
  if command -v "$candidate" >/dev/null &&
    "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))' >/dev/null 2>&1; then
    PYTHON="$(command -v "$candidate")"
    break
  fi
done
[ -n "$PYTHON" ] || die "Python 3.12+ is not installed (https://www.python.org/)"

for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  port_in_use "$port" && die "port $port is already in use (another instance running?)"
done

if ! docker info >/dev/null 2>&1; then
  DOCKER_DESKTOP="/c/Program Files/Docker/Docker/Docker Desktop.exe"
  if [ "$WINDOWS" = 1 ] && [ -f "$DOCKER_DESKTOP" ]; then
    info "Docker is not running, starting Docker Desktop…"
    "$DOCKER_DESKTOP" >/dev/null 2>&1 &
    for _ in $(seq 1 90); do
      docker info >/dev/null 2>&1 && break
      sleep 2
    done
  fi
  docker info >/dev/null 2>&1 || die "Docker is not running. Start Docker Desktop and try again."
fi
info "docker, node $(node --version), $("$PYTHON" --version)"

# --- database -----------------------------------------------------------------

step "Starting Postgres"
docker compose -f "$ROOT/docker/docker-compose.dev.yml" up -d postgres >/dev/null
for _ in $(seq 1 60); do
  docker compose -f "$ROOT/docker/docker-compose.dev.yml" exec -T postgres pg_isready -U soundbarrier -d soundbarrier >/dev/null 2>&1 && break
  sleep 1
done
docker compose -f "$ROOT/docker/docker-compose.dev.yml" exec -T postgres pg_isready -U soundbarrier -d soundbarrier >/dev/null 2>&1 ||
  die "Postgres did not become ready"
info "localhost:5432"

# --- backend ------------------------------------------------------------------

step "Preparing the backend"
cd "$BACKEND"
if [ ! -x "$VENV_BIN/python" ] && [ ! -x "$VENV_BIN/python.exe" ]; then
  info "creating backend/.venv"
  "$PYTHON" -m venv .venv
fi
REQ_MARKER=".venv/.requirements-dev.sha1"
if [ "$(cat "$REQ_MARKER" 2>/dev/null || true)" != "$(file_hash requirements-dev.txt)" ]; then
  info "installing Python dependencies (requirements-dev.txt)"
  "$VENV_BIN/python" -m pip install --quiet --upgrade pip
  "$VENV_BIN/python" -m pip install --quiet -r requirements-dev.txt
  file_hash requirements-dev.txt >"$REQ_MARKER"
fi

if [ ! -f .env ]; then
  info "creating backend/.env with a new secret key"
  secret="$("$VENV_BIN/sound-barrier" gen-secret)"
  sed "s|^SOUND_BARRIER_SECRET_KEY=.*|SOUND_BARRIER_SECRET_KEY=$secret|" .env.example >.env
fi

info "applying database migrations"
"$VENV_BIN/alembic" upgrade head 2>&1 | grep -v "^INFO  \[alembic.runtime.migration\] \(Context impl\|Will assume\)" | sed 's/^/    /' || true

if [ -d "$ROOT/music" ] && [ -z "$("$VENV_BIN/sound-barrier" list-folders)" ]; then
  info "registering ./music as music folder"
  "$VENV_BIN/sound-barrier" add-folder Music "$ROOT/music" | sed 's/^/    /'
fi

# --- frontend -----------------------------------------------------------------

step "Preparing the frontend"
cd "$FRONTEND"
NPM_MARKER="node_modules/.package-lock.sha1"
if [ ! -d node_modules ] || [ "$(cat "$NPM_MARKER" 2>/dev/null || true)" != "$(file_hash package-lock.json)" ]; then
  info "installing npm dependencies"
  npm install --no-audit --no-fund --loglevel=error
  file_hash package-lock.json >"$NPM_MARKER"
fi

# --- run ------------------------------------------------------------------------

PIDS=()

# Runs a command in the background with a colored prefix on each output line.
run() {
  local name="$1" color="$2"
  shift 2
  "$@" > >(sed -u "s/^/${color}[${name}]${RESET} /") 2>&1 &
  PIDS+=("$!")
}

STOPPED=0
stop_all() {
  [ "$STOPPED" = 1 ] && return
  STOPPED=1
  echo
  step "Stopping backend and frontend"
  for pid in "${PIDS[@]}"; do
    if [ "$WINDOWS" = 1 ]; then
      # Git Bash `kill` does not reach Windows child processes (python, node): kill the tree.
      local winpid
      winpid="$(cat "/proc/$pid/winpid" 2>/dev/null || true)"
      [ -n "$winpid" ] && taskkill //PID "$winpid" //T //F >/dev/null 2>&1 || true
    fi
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  info "Postgres is still running (stop it with: ./dev.sh down)"
}
trap stop_all EXIT
trap 'exit 130' INT # the EXIT trap does the cleanup
trap 'exit 143' TERM

step "Starting"
cd "$BACKEND"
PYTHONUNBUFFERED=1 run backend "$MAGENTA" "$VENV_BIN/sound-barrier" serve --port "$BACKEND_PORT"
cd "$FRONTEND"
run frontend "$GREEN" npm run dev -- --port "$FRONTEND_PORT" --strictPort

for _ in $(seq 1 60); do
  curl -fs "http://localhost:$BACKEND_PORT/rest/getOpenSubsonicExtensions?f=json" >/dev/null 2>&1 &&
    curl -fs "http://localhost:$FRONTEND_PORT/" >/dev/null 2>&1 && break
  sleep 1
done

echo
echo "${BOLD}${GREEN}Ready${RESET}"
echo "  Web UI       ${BOLD}http://localhost:$FRONTEND_PORT${RESET}"
echo "  Subsonic API http://localhost:$BACKEND_PORT/rest  (point your Subsonic clients here)"
echo "  Login        admin / admin on a fresh database (change it: backend/.venv/Scripts/sound-barrier set-password admin)"
echo "  ${DIM}Ctrl+C stops the backend and the frontend.${RESET}"
echo

# Stop everything if either process exits on its own.
wait -n "${PIDS[@]}" || true
warn "a process exited, stopping the others"
