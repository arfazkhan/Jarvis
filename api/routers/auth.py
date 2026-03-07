from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from typing import Optional
from api.dependencies import get_system_state, SystemContainer

router = APIRouter()

class ChatRequest(BaseModel):
    """Simple model for demo login (matches legacy structure)"""
    query: str

class Token(BaseModel):
    access_token: str
    token_type: str

@router.post("/token", response_model=Token)
async def login_for_access_token(request: ChatRequest):
    """
    Exchange credentials for a token.
    Note: Ported legacy logic for pilot compatibility.
    """
    if request.query in ["admin", "operator"]:
        # For pilot, we return a simple token.
        # In production, this uses JWT.
        return {"access_token": f"pilot_{request.query}_token", "token_type": "bearer"}
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )
