# syntax=docker/dockerfile:1

############################
# Builder stage
############################
FROM python:3.14-slim AS builder

# Pinned uv from the official distroless image.
COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# 1) Install third-party dependencies only (best layer caching).
#    The lock + manifest are bind-mounted so they never bloat this layer,
#    and the uv download cache is reused across builds.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# 2) Copy the source and install the project itself into the venv.
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


############################
# Runtime stage
############################
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    PATH="/app/.venv/bin:$PATH"

# Non-root user.
RUN groupadd -r app && useradd --no-log-init -r -g app app

WORKDIR /app

# Bring over the virtualenv + app code, owned by the non-root user.
# Same base image as the builder, so the venv's interpreter paths stay valid.
COPY --from=builder --chown=app:app /app /app

USER app

EXPOSE 8000

# Liveness probe — pure stdlib, no curl needed in the slim image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]

# Runs uvicorn via the app entrypoint, which applies proxy-header handling and
# disables the Server header. Configuration is read from the environment.
CMD ["python", "-m", "app"]
