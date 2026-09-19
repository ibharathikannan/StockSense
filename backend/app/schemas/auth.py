from __future__ import annotations

from pydantic import BaseModel, EmailStr

from app.schemas.user import CurrentUser, Password


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: CurrentUser


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: Password
