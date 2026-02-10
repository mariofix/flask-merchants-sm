# Builder stage - use Poetry for proper dependency resolution
FROM python:3.13-slim-bookworm AS builder

WORKDIR /app
ENV POETRY_VERSION=2.2.1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

RUN pip install "poetry==$POETRY_VERSION"

# Copy dependency files
COPY pyproject.toml ./

# Configure Poetry and install dependencies
RUN poetry install --no-interaction --no-root

# Runtime stage
FROM python:3.13-slim-bookworm

# Security and system setup
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd -m -u 1000 -s /bin/bash appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application
COPY --chown=appuser:appuser . .

# Set environment
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1

USER appuser

EXPOSE 80

# Default to Flask, override in compose
CMD ["gunicorn", \
    "--bind", "0.0.0.0:80", \
    "--workers", "4", \
    "--access-logfile", "-", \
    "--error-logfile", "-", \
    "--log-level", "info", \
    "--timeout", "60", \
    "--graceful-timeout", "30", \
    "--keep-alive", "5", \
    "app:app"]
