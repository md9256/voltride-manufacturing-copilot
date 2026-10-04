"""Demo password exchange: password in, signed access token out."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.security import access_required, client_ip, issue_token, login_limiter, password_matches

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str = Field(max_length=200)


class LoginResponse(BaseModel):
    token: str
    expires_at: int  # unix seconds


class AuthStatus(BaseModel):
    required: bool


@router.get("/status", response_model=AuthStatus)
def status() -> AuthStatus:
    return AuthStatus(required=access_required())


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request) -> LoginResponse:
    login_limiter.check(client_ip(request))  # slows down password guessing
    if not access_required():
        raise HTTPException(400, "This deployment has no demo password.")
    if not password_matches(body.password):
        raise HTTPException(401, "Wrong password.")
    token, expires = issue_token()
    return LoginResponse(token=token, expires_at=expires)
