"""兼容入口：应用装配位于 :mod:`app.application`。"""

from .application import (
    app,
    create_app,
    health,
    lifespan,
    settings,
    unhandled_exception,
)
from .database_compat import SQLITE_REQUIRED_COLUMNS

__all__ = [
    "SQLITE_REQUIRED_COLUMNS",
    "app",
    "create_app",
    "health",
    "lifespan",
    "settings",
    "unhandled_exception",
]
