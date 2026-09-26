import os
from typing import Dict, Set, Optional
from dotenv import load_dotenv
from fastapi import Security, HTTPException, status, Depends, Request
from fastapi.security import APIKeyHeader
from enum import Enum

load_dotenv()

API_KEY_NAME = "X-ARVIS-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Request
security_bearer = HTTPBearer(auto_error=False)


class Role(str, Enum):
    """User roles for RBAC."""
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


# Load allowed keys from env
# Format: "key1:role1,key2:role2,key3:role1"
# Backward compatible: "key1,key2,key3" defaults to admin role
def _parse_api_keys() -> Dict[str, Role]:
    """Parse API keys from environment with optional role assignment."""
    keys_config = os.getenv("ARVIS_API_KEYS", "")
    keys_dict: Dict[str, Role] = {}
    
    if not keys_config:
        return keys_dict
    
    for entry in keys_config.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            key, role_name = entry.split(":", 1)
            try:
                keys_dict[key.strip()] = Role(role_name.strip().lower())
            except ValueError:
                # Invalid role, default to viewer for safety
                keys_dict[key.strip()] = Role.VIEWER
        else:
            # Backward compatible: no role specified = admin
            keys_dict[entry] = Role.ADMIN
    
    return keys_dict


API_KEYS: Dict[str, Role] = _parse_api_keys()


def _verify_jwt(token: str) -> Optional[Role]:
    """Verify a Bearer JWT against the shared ARVIS_AUTH_SECRET and return its
    role, or None if invalid. Uses the same secret/algorithm as the token issuer
    so tokens from /auth/token verify here."""
    try:
        from agent_commercial.api.auth import SECRET_KEY, ALGORITHM
        from jose import jwt as _jwt
    except Exception:
        return None
    try:
        payload = _jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        return None
    try:
        return Role(str(payload.get("role", "")).lower())
    except Exception:
        return None


def _resolve_role(key: str) -> Optional[Role]:
    """Role for a credential, resolved fresh each call: a configured API key, or
    a valid signed JWT (decoded + expiry-checked every time — never cached)."""
    if key in API_KEYS:
        return API_KEYS[key]
    return _verify_jwt(key)

# If no keys configured, generate a temporary one for safety (never leave open)
if not API_KEYS:
    import secrets
    temp_key = secrets.token_urlsafe(32)
    print(f"⚠️  WARNING: No ARVIS_API_KEYS set. Generated temp key: {temp_key}")
    API_KEYS[temp_key] = Role.ADMIN


async def get_api_key(
    request: Request,
    api_key_header: Optional[str] = Security(api_key_header),
    token: Optional[str] = None,
    bearer: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer)
) -> str:
    """Validate API Key from header, query param, or Bearer token."""
    # 1. Check Header
    key = api_key_header
    
    # 2. Check Query Param (for SSE/Streaming compatibility)
    if not key:
        key = request.query_params.get("token")
        
    # 3. Check Bearer Token
    if not key and bearer:
        key = bearer.credentials

    if not key:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key or Token",
        )

    # Resolve the role fresh on EVERY request — a static API key OR a signed JWT
    # (re-decoded each time, so expiry is always enforced). The prior version
    # cached verified JWTs into API_KEYS, which meant an expired token kept
    # working after its first use. Never cache tokens.
    if _resolve_role(key) is not None:
        return key

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid API Key",
    )


async def get_admin_key(key: str = Depends(get_api_key)) -> str:
    """Validate Admin-level API Key (requires admin role).

    Resolve the credential through get_api_key via FastAPI DI — the old code
    called get_api_key(api_key_header) positionally, but that function's first
    parameter is the Request, so the key never resolved and valid admin keys got
    403. DI passes the real request/header/bearer correctly."""
    role = _resolve_role(key)

    if role != Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return key


def get_role(api_key: str) -> Optional[Role]:
    """Get the role associated with an API key."""
    return API_KEYS.get(api_key)


def has_permission(api_key: str, required_role: Role) -> bool:
    """Check if an API key has the required role or higher."""
    role = _resolve_role(api_key)
    if not role:
        return False
    
    # Role hierarchy: ADMIN > OPERATOR > VIEWER
    role_hierarchy = {
        Role.ADMIN: 3,
        Role.OPERATOR: 2,
        Role.VIEWER: 1,
    }
    
    return role_hierarchy.get(role, 0) >= role_hierarchy.get(required_role, 0)
