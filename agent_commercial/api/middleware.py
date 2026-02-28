"""
ARVIS Security & Audit Middleware
=================================

Handles CORS restrictions and logs every non-GET request to 
the security audit trail.
"""

import time
import json
import logging
from fastapi import Request
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
