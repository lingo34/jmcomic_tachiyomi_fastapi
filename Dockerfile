# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    APP_HOME=/app

WORKDIR ${APP_HOME}
COPY uv.lock pyproject.toml ./
RUN uv sync --frozen --no-install-project --no-dev -v
