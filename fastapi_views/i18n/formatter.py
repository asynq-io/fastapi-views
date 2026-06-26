from typing import Any, Protocol


class Formatter(Protocol):
    def format(self, text: str, **kwargs: Any) -> str: ...


class StrFormatter:
    def format(self, text: str, **kwargs: Any) -> str:
        return text.format(**kwargs)
