"""PredictIt data models and a parser that tolerates the API's quirks.

Shape (from the public ``/api/marketdata/all/`` feed, documented by third
parties; confirm against the live API before relying on it)::

    {"markets": [{"id", "name", "shortName", "url", "status", "timeStamp",
        "contracts": [{"id", "name", "shortName", "dateEnd", "status",
            "lastTradePrice", "bestBuyYesCost", "bestBuyNoCost",
            "bestSellYesCost", "bestSellNoCost", "lastClosePrice", "displayOrder"}]}]}

The parser accepts camelCase or PascalCase (any key casing), null prices and
``"dateEnd": "NA"``. PredictIt publishes no resolution rules and no order sizes.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from core.fees import UnknownSizeLevel
from core.market_ref import ComparableMarket
from polymarket_client.models import (
    OrderBook, OrderBookSide, TokenOrderBook, TokenType,
)

logger = logging.getLogger(__name__)


def _norm(key: str) -> str:
    return key.replace("_", "").lower()


def _field(data: dict, name: str, default: Any = None) -> Any:
    """Case- and underscore-insensitive key lookup."""
    want = _norm(name)
    for key, value in data.items():
        if _norm(key) == want:
            return value
    return default


def _price(value: Any) -> Optional[float]:
    """A usable price in (0, 1), else None (null, zero or junk means no offer)."""
    try:
        p = float(value)
    except (TypeError, ValueError):
        return None
    return p if 0.0 < p < 1.0 else None


def _date(value: Any) -> Optional[datetime]:
    if not value or str(value).strip().upper() == "NA":
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class PredictItContract:
    id: str
    name: str
    short_name: str = ""
    date_end: Optional[datetime] = None
    status: str = ""
    last_trade_price: Optional[float] = None
    best_buy_yes_cost: Optional[float] = None
    best_buy_no_cost: Optional[float] = None
    best_sell_yes_cost: Optional[float] = None
    best_sell_no_cost: Optional[float] = None
    last_close_price: Optional[float] = None
    display_order: int = 0

    @property
    def is_open(self) -> bool:
        return self.status.strip().lower() == "open"

    @classmethod
    def from_api(cls, data: dict) -> Optional["PredictItContract"]:
        cid = _field(data, "id")
        if cid is None:
            return None
        return cls(
            id=str(cid),
            name=str(_field(data, "name", "") or ""),
            short_name=str(_field(data, "shortName", "") or ""),
            date_end=_date(_field(data, "dateEnd")),
            status=str(_field(data, "status", "") or ""),
            last_trade_price=_price(_field(data, "lastTradePrice")),
            best_buy_yes_cost=_price(_field(data, "bestBuyYesCost")),
            best_buy_no_cost=_price(_field(data, "bestBuyNoCost")),
            best_sell_yes_cost=_price(_field(data, "bestSellYesCost")),
            best_sell_no_cost=_price(_field(data, "bestSellNoCost")),
            last_close_price=_price(_field(data, "lastClosePrice")),
            display_order=int(_field(data, "displayOrder", 0) or 0),
        )


@dataclass
class PredictItMarket:
    id: str
    name: str
    short_name: str = ""
    url: str = ""
    status: str = ""
    timestamp: Optional[datetime] = None
    contracts: list[PredictItContract] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.status.strip().lower() == "open"

    @classmethod
    def from_api(cls, data: dict) -> Optional["PredictItMarket"]:
        mid = _field(data, "id")
        if mid is None:
            return None
        contracts = []
        for raw in _field(data, "contracts", []) or []:
            if isinstance(raw, dict):
                c = PredictItContract.from_api(raw)
                if c is not None:
                    contracts.append(c)
        return cls(
            id=str(mid), name=str(_field(data, "name", "") or ""),
            short_name=str(_field(data, "shortName", "") or ""),
            url=str(_field(data, "url", "") or ""),
            status=str(_field(data, "status", "") or ""),
            timestamp=_date(_field(data, "timeStamp")),
            contracts=contracts,
        )

    @staticmethod
    def contract_key(market_id: str, contract_id: str) -> str:
        return f"{market_id}:{contract_id}"

    def to_comparable(self) -> list[ComparableMarket]:
        """One comparable market per *contract*: each is its own YES/NO bet."""
        out = []
        for c in self.contracts:
            if not c.is_open:
                continue
            title = self.name if c.name.strip().lower() in ("", self.name.lower()) \
                else f"{self.name} — {c.name}"
            out.append(ComparableMarket(
                platform="predictit",
                market_id=self.contract_key(self.id, c.id),
                title=title,
                rules_text="",                       # PredictIt's API carries no rules text
                end_date=c.date_end.isoformat() if c.date_end else "",
                outcome_label=f"YES = {c.name}" if c.name else "",
                resolution_source="",
                url=self.url,
            ))
        return out


def contract_to_orderbook(market_id: str, contract: PredictItContract) -> Optional[OrderBook]:
    """Synthetic single-level book. Sizes are unknown (PredictIt publishes none).

    Asks come from ``bestBuy*Cost``. Bids come from ``bestSell*Cost`` when
    present, otherwise from the complement of the opposite ask.
    """
    yes_ask, no_ask = contract.best_buy_yes_cost, contract.best_buy_no_cost
    yes_bid = contract.best_sell_yes_cost or (round(1 - no_ask, 4) if no_ask else None)
    no_bid = contract.best_sell_no_cost or (round(1 - yes_ask, 4) if yes_ask else None)
    if yes_ask is None and no_ask is None:
        return None

    def side(price: Optional[float]) -> OrderBookSide:
        return OrderBookSide([UnknownSizeLevel(price)] if price else [])

    yes = TokenOrderBook(TokenType.YES, bids=side(yes_bid), asks=side(yes_ask))
    no = TokenOrderBook(TokenType.NO, bids=side(no_bid), asks=side(no_ask))
    return OrderBook(market_id=f"predictit:{market_id}", yes=yes, no=no)


def parse_all(payload: Any) -> list[PredictItMarket]:
    """Parse the ``/marketdata/all`` response (a dict with ``markets``, or a bare list)."""
    raw = _field(payload, "markets", []) if isinstance(payload, dict) else payload
    markets = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        try:
            m = PredictItMarket.from_api(item)
        except Exception as e:
            logger.warning("Skipping unparseable PredictIt market: %s", e)
            continue
        if m is not None:
            markets.append(m)
    return markets
