from __future__ import annotations

import base64
import os
from typing import Annotated, Generic, TypeAlias, TypeVar

from annotated_types import Interval
from pydantic import AfterValidator, Field, PlainSerializer, PositiveInt

from .models import BaseSchema

T = TypeVar("T")

MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", "500"))

PageNumber: TypeAlias = PositiveInt
PageSize = Annotated[int, Interval(gt=0, le=MAX_PAGE_SIZE)]


def encode_cursor(cursor: str) -> str:
    return base64.urlsafe_b64encode(cursor.encode()).decode()


def decode_cursor(cursor: str) -> str:
    try:
        return base64.urlsafe_b64decode(cursor.encode()).decode()
    except (UnicodeDecodeError, ValueError):
        return cursor


Cursor = Annotated[
    str,
    AfterValidator(decode_cursor),
    PlainSerializer(encode_cursor, return_type=str, when_used="json"),
]


class BasePage(BaseSchema, Generic[T]):
    items: list[T] = Field([], description="Array of items")


class CursorPage(BasePage[T]):
    cursor: Cursor | None = Field(None, description="Current page token")
    next_page: Cursor | None = Field(None, description="Next page token")
    previous_page: Cursor | None = Field(None, description="Previous page token")


class NumberedPage(BasePage[T]):
    current_page: int = Field(description="Number of current page")
    page_size: int = Field(description="Number of items returned")
    has_more: bool | None = Field(None, description="Whether more items exist")
    total_pages: int | None = Field(None, description="Total pages available")
    total_items: int | None = Field(None, description="Total items available")


class OffsetPage(BasePage[T]):
    offset: int = Field(description="Offset of the first returned item")
    limit: int = Field(description="Maximum number of items returned")
    has_more: bool | None = Field(None, description="Whether more items exist")
    total_items: int | None = Field(None, description="Total items available")
