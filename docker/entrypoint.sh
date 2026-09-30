#!/bin/sh
# Container entrypoint (spec 03 §3): wait for Postgres, migrate, start the app.
set -eu

cd /app
python -m talos.persistence.wait
alembic upgrade head
exec talos-web "$@"
