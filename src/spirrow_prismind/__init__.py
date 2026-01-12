"""Spirrow-Prismind: Context-aware knowledge management MCP server."""

__version__ = "0.1.0"

from .config import Config, load_config
from .server import PrismindServer, main

__all__ = [
    "Config",
    "load_config",
    "PrismindServer",
    "main",
]
