# Sound-Barrier: backend + web UI in one image, served on port 4040.
# Build from the repository root:  docker build -t sound-barrier .
# Published as dontpanic57/sound-barrier (Docker Hub).

# --- web UI ---------------------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- server ---------------------------------------------------------------------------
FROM python:3.13-slim
ARG VERSION=dev
LABEL org.opencontainers.image.title="Sound-Barrier"       org.opencontainers.image.description="Subsonic-compatible music server with a web player, beets-powered library management, podcasts and audiobooks"       org.opencontainers.image.source="https://github.com/PierreAdam/sound-barrier"       org.opencontainers.image.licenses="MIT"       org.opencontainers.image.version="${VERSION}"

# ffmpeg: FLAC -> MP3 conversion while importing.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/pyproject.toml backend/alembic.ini ./
COPY backend/alembic/ ./alembic/
COPY backend/app/ ./app/
RUN pip install --no-cache-dir --no-deps . && rm -rf build
COPY --from=web /src/dist/ ./web/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

# Mount points: the library, the podcasts and audiobooks folders (optional), the import
# root folder (read-only is fine: imports copy), the beets library, and the application
# data (secret key, covers cache, staging).
RUN mkdir -p /music /podcasts /audiobooks /import /beets /data \
    && chown 1000:1000 /music /podcasts /audiobooks /import /beets /data \
    && chmod 755 /usr/local/bin/entrypoint.sh
ENV PYTHONUNBUFFERED=1 \
    SOUND_BARRIER_DATA_DIR=/data \
    SOUND_BARRIER_WEB_DIR=/app/web \
    SOUND_BARRIER_INITIAL_LIBRARY_DIR=/music \
    SOUND_BARRIER_INITIAL_IMPORT_DIR=/import \
    SOUND_BARRIER_INITIAL_PODCASTS_DIR=/podcasts \
    SOUND_BARRIER_INITIAL_AUDIOBOOKS_DIR=/audiobooks \
    SOUND_BARRIER_BEETS_DIR=/beets
VOLUME ["/data"]

# Runs as an unprivileged user; override with `user:` to match the owner of the music.
USER 1000:1000
EXPOSE 4040
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4040/rest/ping.view', timeout=4)"
ENTRYPOINT ["entrypoint.sh"]
