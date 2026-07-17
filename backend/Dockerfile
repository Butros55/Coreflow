# syntax=docker/dockerfile:1.7
#
# Multi-stage build. `dev` keeps dev dependencies and runs as the reload server;
# `prod` is a slim runtime with gunicorn and no build toolchain.

FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# libpq5 for psycopg, curl for healthchecks/debugging. No compilers: psycopg[binary]
# and reportlab ship wheels, so the runtime stays small.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# ---------------------------------------------------------------------------
# deps — resolved from the lockfile only, so this layer caches across code edits
# ---------------------------------------------------------------------------
FROM base AS deps

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra dev

# ---------------------------------------------------------------------------
# dev
# ---------------------------------------------------------------------------
FROM deps AS dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra dev

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# ---------------------------------------------------------------------------
# prod
# ---------------------------------------------------------------------------
FROM base AS prod

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Run unprivileged: a container escape shouldn't start from root.
RUN groupadd --system --gid 1001 coreflow \
    && useradd --system --uid 1001 --gid coreflow --create-home coreflow \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R coreflow:coreflow /app

# Collect static during build so the image is immutable and startup is fast.
# A throwaway key: this never runs application code, and prod.py would refuse a
# weak key at boot — but collectstatic still needs settings to import.
RUN SECRET_KEY=build-time-only-not-used-at-runtime-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
    ALLOWED_HOSTS=localhost \
    APP_URL=https://localhost \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    python manage.py collectstatic --noinput --clear

USER coreflow

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--worker-class", "gthread", \
     "--threads", "4", \
     "--timeout", "60", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
