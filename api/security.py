import os
from dotenv import load_dotenv
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

load_dotenv()

API_KEY_NAME = "X-ARVIS-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# Load allowed keys from env
# Format: "key1,key2,key3"
ALLOWED_KEYS = set(k.strip() for k in os.getenv("ARVIS_API_KEYS", "").split(",") if k.strip())

# If no keys configured, generate a temporary one for safety (never leave open)
if not ALLOWED_KEYS:
    import secrets
    temp_key = secrets.token_urlsafe(32)
    print(f"⚠️  WARNING: No ARVIS_API_KEYS set. Generated temp key: {temp_key}")
    ALLOWED_KEYS.add(temp_key)

async def get_api_key(api_key_header: str = Security(api_key_header)):
    """Validate API Key from header."""
    if not api_key_header:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key",
        )
    
    if api_key_header not in ALLOWED_KEYS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )
    return api_key_header

async def get_admin_key(api_key_header: str = Security(api_key_header)):
    """Validate Admin-level API Key (subset of keys marked as ADMIN)."""
    # For now, all valid keys are admin. 
    # TODO: Implement RBAC if needed
    return await get_api_key(api_key_header)
