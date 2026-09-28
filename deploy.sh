#!/usr/bin/env bash
# Builds the Docker image on this machine, pushes it to Docker Hub, then updates the
# server over SSH (pull + restart) and checks that the public endpoint answers.
#
#   ./deploy.sh              build, push, deploy
#   ./deploy.sh --check      run the backend and frontend checks first (needs Docker)
#   ./deploy.sh --no-build   deploy the image already on Docker Hub (restart / retry)
#
# Settings: deploy.env next to this script (see deploy.env.example). Needs `docker login`
# on this machine and an SSH key accepted by the server. Git Bash on Windows, or Linux/macOS.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -t 1 ]; then
  BOLD=$'\e[1m' DIM=$'\e[2m' RED=$'\e[31m' GREEN=$'\e[32m' BLUE=$'\e[34m' RESET=$'\e[0m'
else
  BOLD="" DIM="" RED="" GREEN="" BLUE="" RESET=""
fi
step() { echo "${BOLD}${BLUE}==>${RESET} ${BOLD}$*${RESET}"; }
info() { echo "    ${DIM}$*${RESET}"; }
die() { echo "${RED}error:${RESET} $*" >&2; exit 1; }

CHECK=0 BUILD=1
for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --no-build) BUILD=0 ;;
    -h | --help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $arg (see --help)" ;;
  esac
done

[ -f "$ROOT/deploy.env" ] || die "missing deploy.env: copy deploy.env.example and fill it in"
# shellcheck source=/dev/null
. "$ROOT/deploy.env"
: "${IMAGE:?set IMAGE in deploy.env}" "${SSH_HOST:?set SSH_HOST in deploy.env}"
: "${REMOTE_DIR:?set REMOTE_DIR in deploy.env}"
SSH_PORT="${SSH_PORT:-22}"
SERVICE="${SERVICE:-app}"
PUBLIC_URL="${PUBLIC_URL:-}"

remote() { ssh -o BatchMode=yes -o ConnectTimeout=15 -p "$SSH_PORT" "$SSH_HOST" "$@"; }

step "Checking access"
docker info >/dev/null 2>&1 || die "Docker is not running"
remote "test -f '$REMOTE_DIR/docker-compose.yml'" \
  || die "cannot reach $SSH_HOST (port $SSH_PORT) or no docker-compose.yml in $REMOTE_DIR"
info "server $SSH_HOST, stack $REMOTE_DIR"

if [ "$CHECK" = 1 ]; then
  step "Running the checks"
  case "$(uname -s)" in
    MINGW* | MSYS* | CYGWIN*) VENV_BIN="$ROOT/backend/.venv/Scripts" ;;
    *) VENV_BIN="$ROOT/backend/.venv/bin" ;;
  esac
  (cd "$ROOT/backend" && "$VENV_BIN/ruff" format --check . && "$VENV_BIN/ruff" check . \
    && "$VENV_BIN/pyright" && "$VENV_BIN/pytest" -q)
  (cd "$ROOT/frontend" && npm run typecheck && npm test)
fi

# Each deployment also gets a dated tag, to go back to a previous image if needed.
TAG="$(date +%Y%m%d-%H%M%S)"
if [ "$BUILD" = 1 ]; then
  step "Building $IMAGE:latest ($TAG)"
  docker build --platform linux/amd64 -t "$IMAGE:latest" -t "$IMAGE:$TAG" "$ROOT"
  step "Pushing to Docker Hub"
  docker push -q "$IMAGE:$TAG"
  docker push -q "$IMAGE:latest"
fi

step "Deploying on the server"
remote "cd '$REMOTE_DIR' && docker compose pull -q '$SERVICE' && docker compose up -d '$SERVICE'"

step "Waiting for the container to be healthy"
health=""
for _ in $(seq 1 45); do
  health="$(remote "cd '$REMOTE_DIR' && docker inspect -f '{{.State.Health.Status}}' \$(docker compose ps -q '$SERVICE')" 2>/dev/null || true)"
  [ "$health" = healthy ] && break
  sleep 2
done
if [ "$health" != healthy ]; then
  remote "cd '$REMOTE_DIR' && docker compose logs --tail 40 '$SERVICE'" || true
  die "the container is not healthy (status: ${health:-unknown}), logs above"
fi
info "healthy"

if [ -n "$PUBLIC_URL" ]; then
  step "Checking $PUBLIC_URL"
  ping="$(curl -fsS --max-time 15 "$PUBLIC_URL/rest/ping.view?f=json")" \
    || die "$PUBLIC_URL does not answer"
  version="$(echo "$ping" | sed -n 's/.*"serverVersion": *"\([^"]*\)".*/\1/p')"
  curl -fsS --max-time 15 -o /dev/null "$PUBLIC_URL/" || die "the web UI does not load"
  info "Subsonic API and web UI answer (server version ${version:-?})"
fi

[ "$BUILD" = 1 ] && deployed="$IMAGE:$TAG" || deployed="$IMAGE:latest"
echo "${GREEN}${BOLD}Deployed${RESET} $deployed."
