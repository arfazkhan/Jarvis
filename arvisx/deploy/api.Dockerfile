# AllGud / ArvisX API — pilot image for the CHECKLIST product (no sensors, no broker).
# Slim: deterministic floor + REST + optional LLM provider SDKs. No commercial
# vendor step — the K2Think path is the OpenAI-compatible client (openai SDK only).
# Build context = the arvisx/ directory (see deploy/docker-compose.pilot.yml).
FROM python:3.11-slim

WORKDIR /app

# Deps first for layer caching. requirements-llm gives the (lazy) provider SDKs;
# with no key set the agent endpoints degrade to the deterministic floor.
COPY requirements-pilot.txt requirements-llm.txt ./
RUN pip install --no-cache-dir -r requirements-pilot.txt -r requirements-llm.txt

# The ArvisX package → /app/arvisx so `python -m arvisx.api` resolves.
COPY . /app/arvisx/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    ARVISX_API_PORT=8090 \
    ARVISX_SOURCE=sim \
    ARVISX_DB=/data/arvisx.db

VOLUME ["/data"]
EXPOSE 8090

# Liveness: up if the port answers (a 401 when auth is on still counts).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "/app/arvisx/healthcheck.py"]

CMD ["python", "-m", "arvisx.api"]
