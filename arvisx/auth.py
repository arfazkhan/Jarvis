"""
ArvisX auth — lightweight user/role layer for a browser frontend (stdlib only).

The API-key middleware is fine for server-to-server, but a committee-facing SPA can't
safely hold the key and needs per-user roles (owner / fm / viewer). This adds:
  • password hashing (pbkdf2-hmac-sha256, stdlib),
  • compact signed tokens (HMAC-SHA256 — JWT-shaped, no extra deps),
  • a role model: writes require owner/fm; viewer is read-only; the API key = 'system'.

Tokens carry {sub, role, exp}. Verified on every request; login mints them.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional, Tuple

WRITE_ROLES = {"system", "admin", "owner", "fm", "technician"}   # may mutate (technician fills rounds)
ALL_ROLES = {"admin", "owner", "fm", "viewer", "technician"}
ADMIN_ROLES = {"system", "admin"}                       # AllGud operator — admin panel / bot / analytics


def is_admin(role: Optional[str]) -> bool:
    return role in ADMIN_ROLES
TOKEN_TTL = int(os.environ.get("ARVISX_TOKEN_TTL", "86400"))   # seconds


def _secret() -> bytes:
    s = (os.environ.get("ARVISX_AUTH_SECRET") or os.environ.get("ARVISX_API_KEY") or "arvisx-dev-secret")
    return s.encode()


# ── passwords ─────────────────────────────────────────────────────────────
def hash_password(pw: str, iterations: int = 200_000) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, iterations)
    return f"pbkdf2${iterations}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ── tokens (HMAC-signed, JWT-shaped) ───────────────────────────────────────
def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(sub: str, role: str, ttl: int = TOKEN_TTL) -> str:
    payload = {"sub": sub, "role": role, "exp": int(time.time()) + ttl}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def parse_token(token: str) -> Optional[dict]:
    try:
        body, sig = token.split(".")
        expected = _b64e(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64d(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def role_can_write(role: Optional[str]) -> bool:
    return role in WRITE_ROLES


def identify(authorization: str, x_api_key: str, api_key: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (subject, role) for a request. API key → system; else a valid Bearer token.
    (None, None) means unauthenticated."""
    bearer = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    provided_key = x_api_key or (bearer if not bearer.count(".") else "")
    if api_key and provided_key and hmac.compare_digest(provided_key, api_key):
        return ("system", "system")
    if bearer and bearer.count(".") == 1:
        p = parse_token(bearer)
        if p:
            return (p.get("sub"), p.get("role"))
    return (None, None)
