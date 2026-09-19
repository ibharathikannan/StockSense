from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


def paginate(items: list[T], total: int, page: int, page_size: int) -> Page[T]:
    total_pages = max(1, -(-total // page_size))
    return Page[T](items=items, total=total, page=page, page_size=page_size, total_pages=total_pages)
