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
    
    # Allow Pilot Tokens
    if key in ["pilot_admin_token", "pilot_operator_token"]:
        # Map them to internal keys or just return as valid for now
        return key

    if key not in API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )
    return key


async def get_admin_key(api_key_header: str = Security(api_key_header)) -> str:
    """Validate Admin-level API Key (requires admin role)."""
    key = await get_api_key(api_key_header)
    role = API_KEYS.get(key)
    
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
    role = API_KEYS.get(api_key)
    if not role:
        return False
    
    # Role hierarchy: ADMIN > OPERATOR > VIEWER
    role_hierarchy = {
        Role.ADMIN: 3,
        Role.OPERATOR: 2,
        Role.VIEWER: 1,
    }
    
    # Pilot token mapping
    if api_key == "pilot_admin_token":
        current_role = Role.ADMIN
    elif api_key == "pilot_operator_token":
        current_role = Role.OPERATOR
    else:
        current_role = role
        
    return role_hierarchy.get(current_role, 0) >= role_hierarchy.get(required_role, 0)
