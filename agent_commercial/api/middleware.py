"""
ARVIS Security & Audit Middleware
=================================

Handles CORS restrictions and logs every non-GET request to 
the security audit trail.
"""

import time
import json
import logging
import os
from collections import defaultdict
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from agent_commercial.database import get_database

logger = logging.getLogger("arvis.security.audit")

class SecurityAuditMiddleware(BaseHTTPMiddleware):
    """
    Asynchronous middleware to log all commands and 
    sensitive interactions for compliance.
    """
    
    async def dispatch(self, request: Request, call_next):
        # 1. Process Request
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time
        
        # 2. Audit Filter
        # Only audit state-changing operations (POST, PUT, DELETE, PATCH)
        if request.method not in ["GET", "HEAD", "OPTIONS"]:
            try:
                await self._log_audit_trail(request, response, duration)
            except Exception as e:
                logger.error(f"Failed to write audit entry: {e}")
                
        return response

    async def _log_audit_trail(self, request: Request, response, duration: float):
        """Asynchronously write audit record to database"""
        db = get_database()
        
        # Attempt to get user from state if auth middleware ran
        user = getattr(request.state, "user", "anonymous")
        username = user.username if hasattr(user, "username") else "anonymous"
        
        audit_entry = {
            "timestamp": time.time(),
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "user": username,
            "ip": request.client.host if request.client else "unknown",
            "latency_ms": round(duration * 1000, 2)
        }
        
        # Log to structural logger
        logger.info(f"AUDIT | {json.dumps(audit_entry)}")
        
        # Persist to database for compliance queries
        try:
            await db.save_audit_log(
                user=username,
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                ip=request.client.host if request.client else "unknown",
                latency_ms=round(duration * 1000, 2)
            )
        except Exception as e:
            logger.error(f"Failed to persist audit log: {e}")

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Token-bucket rate limiter.
    Protects the chat endpoint from runaway LLM cost — each swarm query
    can trigger 40-50 LLM calls internally.

    Defaults (overridable via env vars):
      ARVIS_RATE_LIMIT_RPM   — requests per minute per IP  (default: 20)
      ARVIS_RATE_LIMIT_BURST — burst allowance             (default: 5)

    Rate-limited paths: /api/v1/chat, /api/v1/advisory
    All other paths: unlimited (health checks, static data).
    """

    RATE_LIMITED_PREFIXES = ("/api/v1/chat", "/api/v1/advisory")

    def __init__(self, app):
        super().__init__(app)
        self.rpm = int(os.getenv("ARVIS_RATE_LIMIT_RPM", "20"))
        self.burst = int(os.getenv("ARVIS_RATE_LIMIT_BURST", "5"))
        self._buckets: dict = defaultdict(lambda: {"tokens": float(self.burst), "last": time.time()})
        self._lock_map: dict = defaultdict(lambda: False)

    def _refill(self, ip: str) -> float:
        """Token-bucket refill. Returns current token count after refill."""
        bucket = self._buckets[ip]
        now = time.time()
        elapsed = now - bucket["last"]
        refill = elapsed * (self.rpm / 60.0)
        bucket["tokens"] = min(float(self.burst), bucket["tokens"] + refill)
        bucket["last"] = now
        return bucket["tokens"]

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if not any(path.startswith(p) for p in self.RATE_LIMITED_PREFIXES):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        tokens = self._refill(ip)

        if tokens < 1.0:
            retry_after = int((1.0 - tokens) / (self.rpm / 60.0)) + 1
            logger.warning(f"Rate limit hit: ip={ip} path={path} tokens={tokens:.2f}")
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Too many requests. Retry after {retry_after}s.",
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        self._buckets[ip]["tokens"] -= 1.0
        return await call_next(request)
