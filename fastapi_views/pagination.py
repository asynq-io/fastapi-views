import base64
import os
from typing import Annotated, Generic, Optional, TypeVar

from annotated_types import Interval
from pydantic import AfterValidator, Field, PlainSerializer, PositiveInt
from typing_extensions import TypeAlias

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


PageToken = Annotated[
    str,
    AfterValidator(decode_cursor),
    PlainSerializer(encode_cursor, return_type=str, when_used="json"),
]


class BasePage(BaseSchema, Generic[T]):
    items: list[T] = Field([], description="Array of items")


class TokenPage(BasePage[T]):
    next_page: Optional[PageToken] = Field(None, description="Next page token")
    previous_page: Optional[PageToken] = Field(None, description="Previous page token")


class NumberedPage(BasePage[T]):
    current_page: int = Field(description="Number of current page")
    page_size: int = Field(description="Number of items returned")
    total_pages: Optional[int] = Field(None, description="Total pages available")
    total_items: Optional[int] = Field(None, description="Total items available")
