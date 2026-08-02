# syntax=docker/dockerfile:1

# ── Builder ─────────────────────────────────────────────────────────────
# Wheels are built in a throwaway stage so the runtime image carries no
# compiler toolchain.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

# ── Runtime ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# curl is used by the container HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser . .

# Git on Windows doesn't preserve the executable bit, so set it here rather
# than relying on the checked-in file mode.
RUN chmod +x /app/docker-entrypoint.sh

USER appuser

# Documentation only — the actual port comes from $PORT at runtime.
EXPOSE 8000

# PaaS platforms (Render, Fly, Cloud Run) inject $PORT and expect the process
# to bind it. Both the healthcheck and the entrypoint honour it, defaulting to
# 8000 for docker-compose and local runs.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8000}/api/v1/health" || exit 1

# CMD rather than ENTRYPOINT so docker-compose can still override it to run
# the Celery worker or a one-off migration.
CMD ["/app/docker-entrypoint.sh"]
