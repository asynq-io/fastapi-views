from ._version import __version__
from .config import configure_app
from .router import ViewRouter

__all__ = [
    "ViewRouter",
    "__version__",
    "configure_app",
]
