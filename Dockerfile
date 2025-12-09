# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENV=/opt/venv \
    UV_LINK_MODE=copy \
    APP_HOME=/app

WORKDIR ${APP_HOME}

# Install uv (static binary)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh -s -- --install-dir /usr/local/bin

# Create runtime venv and non-root user
RUN python -m venv /opt/venv \
    && groupadd -r app && useradd --no-log-init -r -g app app
ENV PATH="/opt/venv/bin:$PATH"

# Copy dependency metadata and install (leverages Docker layer cache)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application source
COPY . .

EXPOSE 8000
USER app

CMD ["uv", "run", "--no-sync", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
