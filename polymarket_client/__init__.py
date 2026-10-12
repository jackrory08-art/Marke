"""
Polymarket Client Module
========================

Provides abstracted access to Polymarket's REST and WebSocket APIs.

``PolymarketClient`` (which pulls in httpx and websockets) is imported lazily so
that ``polymarket_client.models`` can be used without the HTTP stack.
"""

from polymarket_client.models import (
    Market,
    OrderBook,
    Order,
    OrderSide,
    OrderStatus,
    Position,
    Trade,
    PriceLevel,
)

__all__ = [
    "PolymarketClient",
    "Market",
    "OrderBook",
    "Order",
    "OrderSide",
    "OrderStatus",
    "Position",
    "Trade",
    "PriceLevel",
]


def __getattr__(name: str):
    if name == "PolymarketClient":
        from polymarket_client.api import PolymarketClient
        return PolymarketClient
    raise AttributeError(f"module 'polymarket_client' has no attribute {name!r}")
