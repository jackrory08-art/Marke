"""Shared dashboard state and the WebSocket event envelope."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


def make_event(event_type: str, data: Any = None) -> dict:
    """Every event uses the envelope ``{type, ts, data}``."""
    return {
        "type": event_type,
        "ts": datetime.now(timezone.utc).isoformat(),
        "data": {} if data is None else data,
    }


class DashboardState:
    """Holds the current state for the dashboard."""
    
    def __init__(self):
        self.markets: dict = {}
        self.opportunities: list = []
        self.signals: list = []
        self.orders: list = []
        self.trades: list = []
        self.portfolio: dict = {}
        self.risk: dict = {}
        self.stats: dict = {}
        self.timing: dict = {}  # Opportunity timing stats
        self.operational: dict = {}  # Operational stats
        self.is_running: bool = False
        self.mode: str = "dry_run"
        self.last_update: datetime = datetime.utcnow()
        self.started_at: datetime = datetime.utcnow()
        
        # Cross-platform (Polymarket + Kalshi)
        self.cross_platform: dict = {
            "enabled": False,
            "kalshi_markets": 0,
            "polymarket_markets": 0,
            "matched_pairs": 0,
            "kalshi_orderbooks": 0,  # Number of Kalshi orderbooks fetched
            "cross_opportunities": [],
            "matched_pairs_data": [],  # Detailed data for display
            "matching_progress": 0,  # Percentage of matching complete
            "matching_checked": 0,  # Number of comparisons done
            "matching_total": 0,  # Total comparisons to do
            "matching_status": "idle",  # idle, matching, complete
        }
        
        # WebSocket connections, and which session each belongs to
        self._connections: list[WebSocket] = []
        self._socket_sessions: dict[WebSocket, str] = {}
        
        # Cross-platform pairs and AI services (set up by the runner/app)
        self.pair_store = None
        self.ai_status: dict = {"enabled": False, "provider": None, "mock": False}
        self.agent_state: dict = {
            "state": "idle", "detail": "", "progress": {"done": 0, "total": 0}}
        self.log_buffer = None
    
    def to_dict(self) -> dict:
        """Convert state to dictionary for JSON serialization."""
        uptime = (datetime.utcnow() - self.started_at).total_seconds()
        return {
            "markets": self.markets,
            "opportunities": self.opportunities[-50:],  # Last 50
            "signals": self.signals[-50:],
            "orders": self.orders,
            "trades": self.trades[-100:],  # Last 100
            "portfolio": self.portfolio,
            "risk": self.risk,
            "stats": self.stats,
            "timing": self.timing,  # Opportunity timing stats
            "operational": self.operational,  # Operational stats
            "cross_platform": self.cross_platform,  # Cross-platform arbitrage stats
            "is_running": self.is_running,
            "mode": self.mode,
            "last_update": self.last_update.isoformat(),
            "started_at": self.started_at.isoformat(),
            "uptime_seconds": uptime,
        }
    
    def register(self, websocket: WebSocket, session_id: str) -> None:
        self._connections.append(websocket)
        self._socket_sessions[websocket] = session_id
    
    def unregister(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)
        self._socket_sessions.pop(websocket, None)
    
    async def close_session_sockets(self, session_id: str, code: int = 4401) -> None:
        """Close every socket that belongs to a session (logout, expiry)."""
        for ws in [w for w, sid in self._socket_sessions.items() if sid == session_id]:
            try:
                await ws.close(code=code)
            except Exception:
                pass
            self.unregister(ws)
    
    async def broadcast(self, data: dict) -> None:
        """Broadcast an event to all connected WebSocket clients.
        
        ``data`` is ``{type, data}``; a ``ts`` is added when missing so every
        event has the ``{type, ts, data}`` envelope.
        """
        if not self._connections:
            return
        if "ts" not in data:
            data = {**data, "ts": make_event(data.get("type", "event"))["ts"]}
        message = json.dumps(data, default=str)
        
        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except Exception:
                self.unregister(ws)
    
    def emit(self, event_type: str, data: Any = None) -> None:
        """Fire-and-forget broadcast from sync code running inside the event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.broadcast(make_event(event_type, data)))
    
    def add_opportunity(self, opportunity: dict) -> None:
        """Add a new opportunity."""
        opportunity["timestamp"] = datetime.utcnow().isoformat()
        self.opportunities.append(opportunity)
        if len(self.opportunities) > 200:
            self.opportunities = self.opportunities[-100:]
    
    def add_signal(self, signal: dict) -> None:
        """Add a new signal."""
        signal["timestamp"] = datetime.utcnow().isoformat()
        self.signals.append(signal)
        if len(self.signals) > 200:
            self.signals = self.signals[-100:]
    
    def add_trade(self, trade: dict) -> None:
        """Add a new trade."""
        trade["timestamp"] = datetime.utcnow().isoformat()
        self.trades.append(trade)
        if len(self.trades) > 500:
            self.trades = self.trades[-250:]
    
    def add_cross_platform_opportunity(self, opportunity: dict) -> None:
        """Add a cross-platform arbitrage opportunity."""
        opportunity["timestamp"] = datetime.utcnow().isoformat()
        self.cross_platform["cross_opportunities"].append(opportunity)
        if len(self.cross_platform["cross_opportunities"]) > 100:
            self.cross_platform["cross_opportunities"] = self.cross_platform["cross_opportunities"][-50:]
    
    def update_cross_platform_stats(
        self,
        kalshi_markets: int,
        polymarket_markets: int,
        matched_pairs: int,
        enabled: bool = True,
        matched_pairs_data: list = None,
    ) -> None:
        """Update cross-platform statistics."""
        self.cross_platform["enabled"] = enabled
        self.cross_platform["kalshi_markets"] = kalshi_markets
        self.cross_platform["polymarket_markets"] = polymarket_markets
        self.cross_platform["matched_pairs"] = matched_pairs
        if matched_pairs_data is not None:
            self.cross_platform["matched_pairs_data"] = matched_pairs_data




# Global state shared by the bot components and the web app
dashboard_state = DashboardState()
