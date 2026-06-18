"""Hermes Iterative Contextual Refinements plugin."""

from .constants import PLUGIN_VERSION
from .plugin import register

__version__ = PLUGIN_VERSION

__all__ = ["__version__", "register"]
