"""Base class for data sources."""

import platform
from abc import ABC, abstractmethod


class Source(ABC):
    name: str  # "browser", "texts", etc.
    description: str  # Human-readable
    platform_required: str | None = None  # "Darwin" for macOS-only, None for any

    @abstractmethod
    def collect(self, since_dt, until_dt=None) -> str | None:
        ...

    def is_available(self) -> bool:
        return self.platform_required is None or platform.system() == self.platform_required
