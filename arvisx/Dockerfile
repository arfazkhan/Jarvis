# ArvisX API — pilot image (with the commercial LLM layer vendored in).
# Build context = the arvisx/ directory (see docker-compose.yml).
#
# PREREQUISITE: run `python scripts/vendor_commercial.py` first so arvisx/vendor/
# holds the minimal commercial packages (agent_home + agent_unified, ~0.3 MB).
# The image stays slim — provider SDKs are pip deps, no torch/faiss/whisper.
FROM python:3.11-slim

WORKDIR /app

# Deps first for layer caching: deterministic floor + LLM provider SDKs.
COPY requirements-pilot.txt requirements-llm.txt ./
RUN pip install --no-cache-dir -r requirements-pilot.txt -r requirements-llm.txt

# Vendored commercial packages → /app top-level so `agent_home` / `agent_unified`
# import cleanly (UnifiedLLM). They sit next to the arvisx package on sys.path.
COPY vendor/agent_home   /app/agent_home
COPY vendor/agent_unified /app/agent_unified

# The ArvisX package itself → /app/arvisx so `python -m arvisx.api` resolves.
COPY . /app/arvisx/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    ARVISX_API_PORT=8090 \
    ARVISX_DB=/data/arvisx.db

# Persist the SQLite DB (events/baselines/work orders/skills) on a volume.
VOLUME ["/data"]
EXPOSE 8090

# Liveness: server is up if the port answers at all (even a 401 when auth is on).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "/app/arvisx/healthcheck.py"]

CMD ["python", "-m", "arvisx.api"]
