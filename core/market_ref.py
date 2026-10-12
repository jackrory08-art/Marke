"""Normalised, platform-neutral view of a market's text.

``ComparableMarket`` holds exactly the fields an LLM (or a human) needs to
decide whether two contracts resolve on the same terms. It is also the
*whitelist* for what is ever sent to a model: nothing else (no config, keys or
environment) can reach a prompt through it.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

MAX_FIELD_CHARS = 4000
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    """Strip control characters and cut to ``limit`` characters."""
    if value is None:
        return ""
    text = _CONTROL_CHARS.sub("", str(value)).strip()
    return text[:limit]


def _iso(dt: Optional[datetime]) -> str:
    return dt.isoformat() if isinstance(dt, datetime) else ""


@dataclass(frozen=True)
class ComparableMarket:
    platform: str
    market_id: str
    title: str
    rules_text: str = ""
    end_date: str = ""          # ISO 8601 or empty
    outcome_label: str = ""     # what "YES" means / the outcome list
    resolution_source: str = ""
    url: str = ""

    @property
    def has_rules(self) -> bool:
        return bool(self.rules_text.strip())

    def prompt_dict(self) -> dict:
        """The only fields that may be shown to a model (cleaned and truncated)."""
        return {
            "platform": clean_text(self.platform, 32),
            "title": clean_text(self.title),
            "rules_text": clean_text(self.rules_text),
            "rules_available": self.has_rules,
            "end_date": clean_text(self.end_date, 64),
            "outcome_label": clean_text(self.outcome_label),
            "resolution_source": clean_text(self.resolution_source),
        }

    def key_dict(self) -> dict:
        """Fields that decide a verdict; used for the cache key."""
        return {
            "title": clean_text(self.title),
            "rules_text": clean_text(self.rules_text),
            "end_date": clean_text(self.end_date, 64),
            "outcome_label": clean_text(self.outcome_label),
            "resolution_source": clean_text(self.resolution_source),
        }

    def to_public(self) -> dict:
        d = self.prompt_dict()
        d["market_id"] = self.market_id
        d["url"] = self.url
        return d


def from_polymarket(market) -> ComparableMarket:
    outcomes = getattr(market, "outcomes", None) or []
    slug = getattr(market, "slug", "")
    return ComparableMarket(
        platform="polymarket",
        market_id=market.market_id,
        title=market.question,
        rules_text=market.description or "",
        end_date=_iso(market.end_date),
        outcome_label=" / ".join(outcomes) if outcomes else "",
        resolution_source=getattr(market, "resolution_source", "") or "",
        url=f"https://polymarket.com/market/{slug}" if slug else "",
    )


def from_kalshi(market) -> ComparableMarket:
    rules = "\n".join(p for p in (market.rules_primary, market.rules_secondary) if p)
    title = market.title
    label = market.yes_sub_title or market.subtitle or ""
    return ComparableMarket(
        platform="kalshi",
        market_id=market.ticker,
        title=title,
        rules_text=rules,
        end_date=_iso(market.expiration_time or market.close_time),
        outcome_label=f"YES = {label}" if label else "",
        resolution_source="",
        url=f"https://kalshi.com/markets/{market.ticker.lower()}" if market.ticker else "",
    )
