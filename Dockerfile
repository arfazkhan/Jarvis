# ═══════════════════════════════════════════════════════════════════════════════
# ARVIS Ops Copilot - Production Docker Image
# ═══════════════════════════════════════════════════════════════════════════════
# Multi-stage build for optimized production image
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# Stage 1: Builder
# ═══════════════════════════════════════════════════════════════════════════════
FROM python:3.11-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ═══════════════════════════════════════════════════════════════════════════════
# Stage 2: Production Image
# ═══════════════════════════════════════════════════════════════════════════════
FROM python:3.11-slim as production

# Labels for container metadata
LABEL maintainer="ARVIS Team"
LABEL version="1.0.0"
LABEL description="ARVIS Ops Copilot - AI-powered Building Management System"
LABEL org.opencontainers.image.source="https://github.com/arvis/arvis-ops-copilot"

# Create non-root user for security
RUN groupadd -r arvis && useradd -r -g arvis arvis

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Audio support (for TTS)
    libsndfile1 \
    ffmpeg \
    # Network utilities
    curl \
    # BACnet support
    libbacnet-1.0.0 || true \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Create necessary directories
RUN mkdir -p /app/data /app/logs /app/config && \
    chown -R arvis:arvis /app

# Copy application code
COPY --chown=arvis:arvis . .

# Copy configuration
COPY config/ /app/config/

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENV=production \
    DEBUG=false \
    LOG_LEVEL=INFO

# Switch to non-root user
USER arvis

# Expose ports
# 8000: Main API
# 9090: Prometheus metrics
EXPOSE 8000 9090

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command
CMD ["python", "-m", "agent_commercial.main", "--mode", "api_only", "--port", "8000"]

# ═══════════════════════════════════════════════════════════════════════════════
# Stage 3: Development Image (Optional)
# ═══════════════════════════════════════════════════════════════════════════════
FROM production as development

USER root

# Install development dependencies
RUN pip install --no-cache-dir \
    black \
    flake8 \
    mypy \
    pytest \
    pytest-cov \
    pytest-asyncio

# Enable debug mode
ENV DEBUG=true \
    LOG_LEVEL=DEBUG

USER arvis

# Development command with auto-reload
CMD ["python", "-m", "agent_commercial.main", "--mode", "simulator", "--port", "8000"]
