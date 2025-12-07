from importlib.metadata import version

from .config import configure_app
from .router import ViewRouter

__version__ = version(__name__)


__all__ = [
    "ViewRouter",
    "__version__",
    "configure_app",
]
