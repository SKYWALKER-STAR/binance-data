"""Strategy engine runtime loop.

This module provides backward compatibility by re-exporting the original
StrategyEngine class (now an alias for FuturesStrategyEngine).

For new code, prefer using the specific engine classes:
    - FuturesStrategyEngine: U本位合约引擎
    - SpotStrategyEngine: 现货引擎
"""

from __future__ import annotations

from .base import EngineConfig
from .futures import FuturesStrategyEngine

# Backward compatibility: StrategyEngine is an alias for FuturesStrategyEngine
StrategyEngine = FuturesStrategyEngine

__all__ = ["EngineConfig", "StrategyEngine", "FuturesStrategyEngine"]
