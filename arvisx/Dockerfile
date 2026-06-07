# ArvisX API — pilot image. Deterministic floor, no commercial stack.
# Build context = the arvisx/ directory (see docker-compose.yml).
FROM python:3.11-slim

WORKDIR /app

# Deps first for layer caching.
COPY requirements-pilot.txt ./
RUN pip install --no-cache-dir -r requirements-pilot.txt

# Copy the package into /app/arvisx so `python -m arvisx.api` resolves.
COPY . /app/arvisx/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ARVISX_API_PORT=8090 \
    ARVISX_DB=/data/arvisx.db

# Persist the SQLite DB (events/baselines/work orders/skills) on a volume.
VOLUME ["/data"]
EXPOSE 8090

# Liveness: server is up if the port answers at all (even a 401 when auth is on).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "/app/arvisx/healthcheck.py"]

CMD ["python", "-m", "arvisx.api"]
