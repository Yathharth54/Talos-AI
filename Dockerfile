# syntax=docker/dockerfile:1
# Talos web app image (spec 03 §3). Build: `docker build .` (runtime target).
# Stages: frontend (Vite build) → deps (uv venv) → test (dev extras, for
# compose.test.yml) → runtime (what `docker compose up` runs).

# ---- 1. frontend: build frontend/dist ----------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. deps: the Python venv at /app/.venv -------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS deps
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# Third-party packages first, so source edits don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
# The project itself, installed editable: talos/ must stay at /app/talos,
# because settings.PROJECT_ROOT (alembic.ini, alembic/) is derived from it.
COPY README.md LICENSE ./
COPY talos/ ./talos/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- 3. test: deps + dev extras + tests (compose.test.yml) ---------------------
FROM deps AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra dev
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY tests/ ./tests/
COPY docs/superpowers/specs/reference/ ./docs/superpowers/specs/reference/
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
CMD ["pytest", "-q"]

# ---- 4. runtime -----------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime
RUN useradd --uid 1000 --user-group --create-home --shell /usr/sbin/nologin talos \
    && mkdir -p /data/vault/tools /data/workspace \
    && chown -R talos:talos /data
WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
COPY talos/ ./talos/
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY --chmod=755 docker/entrypoint.sh /app/docker/entrypoint.sh
COPY --from=frontend /frontend/dist /app/frontend/dist
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TALOS_VAULT_DIR=/data/vault \
    TALOS_WORKSPACE_DIR=/data/workspace \
    TALOS_DOTENV_PATH=/data/.env \
    TALOS_WEB_HOST=0.0.0.0 \
    TALOS_WEB_PORT=8000
USER talos
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"]
ENTRYPOINT ["/app/docker/entrypoint.sh"]
