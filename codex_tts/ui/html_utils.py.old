"""Compat layer for moved HTML helpers."""

from ..text import html_utils as _html_utils

__all__ = [name for name in dir(_html_utils) if not name.startswith("__")]
globals().update({name: getattr(_html_utils, name) for name in __all__})
