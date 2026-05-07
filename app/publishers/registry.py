"""Registry mapping platform name → driver class."""
from __future__ import annotations

from typing import Optional, Type

from .base import PlatformDriver
from .xvideos_driver import XVideosDriver
from .pornhub_driver import PornhubDriver
from .xnxx_driver import XnxxDriver
from .xhamster_driver import XhamsterDriver

DRIVER_REGISTRY: dict[str, Type[PlatformDriver]] = {
    "xvideos": XVideosDriver,
    "pornhub": PornhubDriver,
    "xnxx": XnxxDriver,
    "xhamster": XhamsterDriver,
}


def get_driver(platform: str) -> Optional[Type[PlatformDriver]]:
    """Return driver class for the given platform name, or None if unsupported."""
    return DRIVER_REGISTRY.get(platform.lower())


SUPPORTED_PLATFORMS = list(DRIVER_REGISTRY.keys())
