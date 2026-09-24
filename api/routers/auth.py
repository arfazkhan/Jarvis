import os
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from datetime import timedelta

# Reuse the real JWT machinery (single shared secret + algorithm) so tokens this
# endpoint issues verify everywhere ARVIS checks auth.
from agent_commercial.api.auth import create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter()


class LoginRequest(BaseModel):
    """Credentials for login. Password is REQUIRED — no password-free access."""
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


# Passwords come from the environment ONLY. If unset, that role cannot log in
# (fail closed) — never a hardcoded or password-free credential.
def _expected_password(username: str) -> Optional[str]:
    mapping = {
        "admin": os.getenv("ARVIS_ADMIN_PASSWORD", "").strip(),
        "operator": os.getenv("ARVIS_OPERATOR_PASSWORD", "").strip(),
        "viewer": os.getenv("ARVIS_VIEWER_PASSWORD", "").strip(),
    }
    return mapping.get(username.lower()) or None


@router.post("/token", response_model=Token)
async def login_for_access_token(request: LoginRequest):
    """Exchange a username + password for a short-lived signed JWT.

    SECURITY: replaces the previous password-free path that returned a fixed
    'pilot_<role>_token'. Credentials are checked against env-configured
    passwords (fail closed if unset); the token is a real HS256 JWT carrying the
    role claim, verified by the shared ARVIS_AUTH_SECRET.
    """
    username = request.username.strip().lower()
    expected = _expected_password(username)

    # constant-ish comparison; reject if no password configured for this role
    import hmac
    if not expected or not hmac.compare_digest(request.password, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        {"sub": username, "role": username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": token, "token_type": "bearer"}
