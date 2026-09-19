from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, EmailStr, Field

from app.core.security import MAX_PASSWORD_BYTES


def _password_fits_bcrypt(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")
    return value


# 8+ characters and within bcrypt's 72-byte input limit.
Password = Annotated[str, Field(min_length=8), AfterValidator(_password_fits_bcrypt)]


class UserOut(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None
    last_login_at: datetime | None = None

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "UserOut":
        return cls(
            id=str(doc["_id"]),
            email=doc["email"],
            full_name=doc.get("full_name", ""),
            role=doc["role"],
            is_active=doc.get("is_active", True),
            created_at=doc["created_at"],
            updated_at=doc.get("updated_at"),
            last_login_at=doc.get("last_login_at"),
        )


class CurrentUser(UserOut):
    """The signed-in user plus the permissions their role grants."""

    permissions: list[str]


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=100)
    password: Password
    role: str = "user"
    is_active: bool = True


class UserUpdate(BaseModel):
    """PATCH body — only the fields that are sent are changed."""

    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: str | None = None
    is_active: bool | None = None
    password: Password | None = None  # admin-initiated password reset
