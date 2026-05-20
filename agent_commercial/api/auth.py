"""
ARVIS Authentication & RBAC
===========================

Handles JWT token generation, password hashing (placeholder), 
and role-based access control for API routes.
"""

import os
from datetime import datetime, timedelta
from typing import Optional, List
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

# Configuration (In production, use environment variables)
_secret = os.getenv("ARVIS_AUTH_SECRET")
if not _secret:
    import sys
    # In production crash hard — a missing secret means tokens can be forged.
    # In development, allow a loud warning + generated ephemeral secret so the
    # server still starts without requiring env setup.
    if os.getenv("ARVIS_ENV", "development").lower() == "production":
        print("FATAL: ARVIS_AUTH_SECRET env var not set. Refusing to start in production.", file=sys.stderr)
        sys.exit(1)
    import secrets as _secrets
    _secret = _secrets.token_hex(32)
    import logging as _logging
    _logging.getLogger("arvis.auth").warning(
        "ARVIS_AUTH_SECRET not set — generated ephemeral secret. "
        "Tokens will be invalidated on restart. Set ARVIS_AUTH_SECRET for production."
    )
SECRET_KEY = _secret
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/token")

class User(BaseModel):
    username: str
    role: str  # admin, operator, viewer
    full_name: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Generate a high-entropy JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Dependency to validate token and return user identity"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None or role is None:
            raise credentials_exception
        token_data = TokenData(username=username, role=role)
    except JWTError:
        raise credentials_exception
        
    # In production, check database for user validity
    return User(username=token_data.username, role=token_data.role)

def require_role(allowed_roles: List[str]):
    """Decorator-style dependency for RBAC"""
    async def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires one of these roles: {allowed_roles}"
            )
        return current_user
    return role_checker
