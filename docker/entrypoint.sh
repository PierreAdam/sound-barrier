#!/bin/sh
# Container start: secret key, database migrations, then the server.
set -eu

data_dir="${SOUND_BARRIER_DATA_DIR:-/data}"
if [ ! -w "$data_dir" ]; then
    echo "The data folder $data_dir is not writable by uid $(id -u): fix its owner or set 'user:'." >&2
    exit 1
fi

# The key encrypts user passwords: generated once and kept in the data folder, unless
# given in SOUND_BARRIER_SECRET_KEY. Losing it means resetting every password.
if [ -z "${SOUND_BARRIER_SECRET_KEY:-}" ]; then
    key_file="$data_dir/secret.key"
    if [ ! -s "$key_file" ]; then
        (umask 077 && sound-barrier gen-secret > "$key_file")
        echo "Generated a new secret key in $key_file (back it up with the database)."
    fi
    SOUND_BARRIER_SECRET_KEY="$(cat "$key_file")"
    export SOUND_BARRIER_SECRET_KEY
fi

# Postgres may still be starting: retry the migrations for about a minute.
cd /app
attempt=1
until alembic upgrade head; do
    if [ "$attempt" -ge 30 ]; then
        echo "Database migrations failed, giving up." >&2
        exit 1
    fi
    echo "Database not ready, retrying in 2 s ($attempt/30)..."
    attempt=$((attempt + 1))
    sleep 2
done

exec sound-barrier serve --port 4040 "$@"
