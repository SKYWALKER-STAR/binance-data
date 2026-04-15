"""Strategy engine package."""

from .base import BaseStrategyEngine, EngineConfig
from .core import StrategyEngine
from .futures import FuturesStrategyEngine
from .spot import SpotStrategyEngine

__all__ = [
    "BaseStrategyEngine",
    "EngineConfig",
    "StrategyEngine",  # Backward compatibility alias for FuturesStrategyEngine
    "FuturesStrategyEngine",
    "SpotStrategyEngine",
]
