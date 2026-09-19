from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.permissions import effective_permissions

# Role names are URL-safe keys, e.g. "support-agent". Immutable once created.
ROLE_NAME_PATTERN = r"^[a-z][a-z0-9_-]{1,29}$"


class RoleOut(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str]
    is_system: bool
    user_count: int = 0
    created_at: datetime
    updated_at: datetime | None = None

    @classmethod
    def from_doc(cls, doc: dict[str, Any], user_count: int = 0) -> "RoleOut":
        return cls(
            name=doc["name"],
            description=doc.get("description"),
            permissions=sorted(effective_permissions(doc)),
            is_system=doc.get("is_system", False),
            user_count=user_count,
            created_at=doc["created_at"],
            updated_at=doc.get("updated_at"),
        )


class RoleOption(BaseModel):
    name: str
    description: str | None = None


class PermissionOut(BaseModel):
    key: str
    description: str
    group: str


class RoleCreate(BaseModel):
    name: str = Field(pattern=ROLE_NAME_PATTERN, description="lowercase key, 2-30 chars: a-z 0-9 _ -")
    description: str | None = Field(default=None, max_length=300)
    permissions: list[str] = []


class RoleUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=300)
    permissions: list[str] | None = None
