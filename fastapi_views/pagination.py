import base64
import os
from typing import Annotated, Generic, Optional, TypeVar

from annotated_types import Interval
from pydantic import AfterValidator, PlainSerializer

from .schemas import BaseSchema

T = TypeVar("T")

MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", 500))

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


class TokenPage(BaseSchema, Generic[T]):
    items: list[T] = []
    next_page: Optional[PageToken] = None
    previous_page: Optional[PageToken] = None


class NumberedPage(BaseSchema, Generic[T]):
    items: list[T] = []
    current_page: int
    page_size: int
    total_pages: Optional[int] = None
    total_items: Optional[int] = None
