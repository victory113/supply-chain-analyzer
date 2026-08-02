#!/bin/sh
#
# Container entrypoint: migrate, then serve.
#
# This lives in a script rather than a platform's inline command field because
# nesting `sh -c "a && b"` inside a host that already runs the command through
# a shell is fragile — the quoting collapses and the whole string gets treated
# as one program name (exit 127). A script has no such ambiguity, and it means
# the image behaves identically on Render, Fly, Cloud Run, or plain `docker run`.
set -e

# Free-tier hosts have no pre-deploy hook, so migrations run here. Alembic is a
# no-op when the schema is already current, making this safe on every restart.
# Set RUN_MIGRATIONS=0 for replicas that shouldn't race to migrate.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "entrypoint: applying database migrations"
  alembic upgrade head
fi

# PaaS platforms assign the port at runtime; 8000 is the local default.
echo "entrypoint: starting API on port ${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
