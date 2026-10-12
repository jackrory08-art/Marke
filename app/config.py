"""Configuration dataclasses for the web app, database, AI and PredictIt.

These are plain dataclasses (no third-party imports) so that
``utils.config_loader`` can include them without pulling in the web stack.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ServerConfig:
    """Dashboard HTTP server and session settings."""
    host: str = "127.0.0.1"
    port: int = 8000
    cookie_secure: bool = True
    session_idle_minutes: int = 120
    session_absolute_hours: int = 12
    allowed_origins: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=lambda: ["127.0.0.1", "localhost"])
    hsts: bool = False


@dataclass
class DatabaseConfig:
    """Database connection. ``DATABASE_URL`` in the environment overrides ``url``."""
    url: str = "sqlite:///data/marke.db"
    auto_migrate: bool = True


@dataclass
class AIConfig:
    """LLM match verifier and opportunity analyst."""
    enabled: bool = True
    provider: str = "gemini"            # gemini | anthropic | mock
    model: str = "gemini-3.1-flash-lite"
    # None = leave at the provider default (Google advises against lowering
    # temperature for Gemini 3.x). Repeatability comes from the strict schema,
    # the verdict cache and a low thinking level.
    temperature: Optional[float] = None
    thinking_level: str = "low"
    max_output_tokens: int = 1024

    # Gate thresholds
    min_confidence: float = 0.80
    min_confidence_caveats: float = 0.90

    # Throttling / budget (defaults sit under the Flash-Lite free-tier quota)
    max_concurrency: int = 2
    requests_per_minute: int = 10
    max_retries: int = 3
    daily_call_budget: int = 400
    daily_cost_budget_usd: float = 0.0  # 0 = no cost cap
    error_backoff_minutes: int = 15
    # USD per million tokens, keyed by model id. Estimates: check Google's
    # pricing page and override here if they differ.
    pricing: dict = field(default_factory=lambda: {
        "gemini-3.1-flash-lite": {"input_per_mtok": 0.10, "output_per_mtok": 0.40},
    })

    # Analyst
    analysis_enabled: bool = True
    analysis_min_interval_s: int = 900
    verifier_reserve_pct: int = 40



@dataclass
class PredictItConfig:
    """PredictIt read-only data source (off by default)."""
    enabled: bool = False
    api_url: str = "https://www.predictit.org/api/marketdata/all/"
    poll_interval_s: int = 60
    min_net_edge: float = 0.05
    max_contract_usd: float = 850.0
    profit_fee_pct: float = 0.10
    withdrawal_fee_pct: float = 0.05
    apply_withdrawal_fee: bool = False
    timeout_s: float = 15.0
    max_retries: int = 3
