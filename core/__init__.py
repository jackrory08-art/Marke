"""
Core Trading Engine Module
===========================

Contains the main trading logic components:
- DataFeed: Real-time market data streaming
- ArbEngine: Arbitrage and spread opportunity detection
- ExecutionEngine: Order management and placement
- RiskManager: Position and loss limits
- Portfolio: Inventory and PnL tracking

The names below are imported lazily (PEP 562) so that importing a light
submodule such as ``core.ai`` or ``core.fees`` does not pull in the trading
engine.
"""

import importlib

_LAZY = {
    "DataFeed": "core.data_feed",
    "ArbEngine": "core.arb_engine",
    "ExecutionEngine": "core.execution",
    "RiskManager": "core.risk_manager",
    "Portfolio": "core.portfolio",
}

__all__ = list(_LAZY)


def __getattr__(name: str):
    if name in _LAZY:
        return getattr(importlib.import_module(_LAZY[name]), name)
    raise AttributeError(f"module 'core' has no attribute {name!r}")
