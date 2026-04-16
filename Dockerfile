# syntax=docker/dockerfile:1.7
#
# Multi-stage build for the combined MERON server (Dash UI + REST API).
# Stage 1 builds a wheel of the app + all its deps; stage 2 is the
# minimal runtime. Running as a non-root user, with /data as the
# persistence root (mount a host volume here).

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# System deps for wheels that need compilation (scipy, cryptography, etc.).
# Removed in the runtime stage, so they don't bloat the final image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY strava_analytics ./strava_analytics

RUN pip install --prefix=/install ".[web,api]" gunicorn

# ──────────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MERON_DB_PATH=/data/meron.db \
    PORT=8050

# Non-root user. UID/GID 1000 is conventional and keeps bind-mounted
# volumes owned by the host user on most Linux setups.
RUN groupadd --system --gid 1000 meron \
    && useradd --system --uid 1000 --gid meron --create-home meron \
    && mkdir -p /data \
    && chown meron:meron /data

COPY --from=builder /install /usr/local

WORKDIR /app
COPY --chown=meron:meron strava_analytics ./strava_analytics
COPY --chown=meron:meron pyproject.toml ./

USER meron

EXPOSE 8050

# Run migrations on boot (idempotent), then start gunicorn. The WSGI
# module calls data.init(None) during import so the Dash layout can
# render on the first request.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 60 --access-logfile - strava_analytics.web.wsgi:app"]
