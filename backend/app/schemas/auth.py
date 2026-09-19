from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import CurrentUser, Password


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    """Public self-signup. There is deliberately no `role`: new accounts are always normal users."""

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=100)
    password: Password  # 8+ chars, within bcrypt's 72-byte limit


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: CurrentUser


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: Password
