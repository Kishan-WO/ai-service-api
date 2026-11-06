# Multi-stage Dockerfile using Astral uv
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install dependencies first (for optimal Docker layer caching)
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy application source code
COPY . .
RUN uv sync --frozen --no-dev


# Runner stage
FROM python:3.14-slim-bookworm AS runner

WORKDIR /app

# Create a non-root user for security best practices
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy virtual environment from builder stage
COPY --from=builder --chown=appuser:appuser /app /app

# Place virtual environment on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

# Start FastAPI server using uvicorn
CMD ["uvicorn", "ai_service.main:app", "--host", "0.0.0.0", "--port", "8000"]

