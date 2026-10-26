# =============================================================================
# DSRT Core — Production Docker Image
# Multi-stage: builder → runtime (minimal attack surface)
# =============================================================================

# --- Stage 1: Builder ---
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt* ./
RUN pip install --no-cache-dir --prefix=/install . 2>/dev/null || \
    pip install --no-cache-dir --prefix=/install -r requirements.txt 2>/dev/null || \
    pip install --no-cache-dir --prefix=/install fastapi uvicorn sqlalchemy asyncpg pydantic pydantic-settings

COPY . /build

# --- Stage 2: Runtime ---
FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r dsrt && useradd -r -g dsrt -d /app -s /sbin/nologin dsrt

COPY --from=builder /install /usr/local
COPY --from=builder /build /app

WORKDIR /app

# Create dsrt schema init script
RUN mkdir -p /app/storage && chown -R dsrt:dsrt /app

USER dsrt

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "core.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--log-level", "info"]