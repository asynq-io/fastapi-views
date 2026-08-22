from importlib.metadata import version

from .config import configure_app
from .permissions import (
    AllowAny,
    Authenticated,
    BasePermission,
    CurrentUser,
    HasPermissions,
    IsAdmin,
    IsAdminOrOwner,
    IsAuthenticated,
    IsOwner,
    Principal,
)
from .router import ViewRouter

__version__ = version(__name__)


__all__ = [
    "AllowAny",
    "Authenticated",
    "BasePermission",
    "CurrentUser",
    "HasPermissions",
    "IsAdmin",
    "IsAdminOrOwner",
    "IsAuthenticated",
    "IsOwner",
    "Principal",
    "ViewRouter",
    "__version__",
    "configure_app",
]
