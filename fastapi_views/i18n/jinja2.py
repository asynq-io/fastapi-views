from typing import Any

from jinja2 import Environment, StrictUndefined


class JinjaFormatter:
    def __init__(
        self, env: Environment = Environment(undefined=StrictUndefined, autoescape=True)
    ) -> None:
        self._env = env

    def format(self, text: str, **kwargs: Any) -> str:
        template = self._env.from_string(text)
        return template.render(**kwargs)
