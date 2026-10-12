"""
Configuration Loader
=====================

Loads and validates configuration from YAML files.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from app.config import AIConfig, DatabaseConfig, PredictItConfig, ServerConfig

logger = logging.getLogger(__name__)

# Credentials must come from the environment (or .env), not config.yaml.
_SECRET_ENV_MAP = {
    "api_key": "POLYMARKET_API_KEY",
    "api_secret": "POLYMARKET_API_SECRET",
    "passphrase": "POLYMARKET_PASSPHRASE",
    "private_key": "POLYMARKET_PRIVATE_KEY",
}


class ConfigError(Exception):
    """Configuration error."""
    pass


@dataclass
class ApiConfig:
    """API configuration."""
    polymarket_rest_url: str = "https://clob.polymarket.com"
    polymarket_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    gamma_api_url: str = "https://gamma-api.polymarket.com"
    kalshi_api_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""
    private_key: str = ""
    timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_delay_seconds: float = 1.0


@dataclass
class TradingConfig:
    """Trading configuration."""
    markets: list[str] = field(default_factory=list)
    min_edge: float = 0.01
    bundle_arb_enabled: bool = True
    min_spread: float = 0.05
    tick_size: float = 0.01
    mm_enabled: bool = True
    default_order_size: float = 50.0
    min_order_size: float = 5.0
    max_order_size: float = 200.0
    slippage_tolerance: float = 0.02
    order_timeout_seconds: float = 60.0


@dataclass
class RiskConfig:
    """Risk configuration."""
    max_position_per_market: float = 200.0
    max_global_exposure: float = 5000.0
    max_daily_loss: float = 500.0
    max_drawdown_pct: float = 0.10
    trade_only_high_volume: bool = True
    min_24h_volume: float = 10000.0
    whitelist: list[str] = field(default_factory=list)
    blacklist: list[str] = field(default_factory=list)
    kill_switch_enabled: bool = True
    auto_unwind_on_breach: bool = False


@dataclass
class ModeConfig:
    """Trading mode configuration."""
    trading_mode: str = "dry_run"  # "live" or "dry_run"
    data_mode: str = "real"  # "real" or "simulation" - use simulation for demos
    cross_platform_enabled: bool = True  # Enable cross-platform arbitrage (Polymarket + Kalshi)
    kalshi_enabled: bool = True  # Enable Kalshi market monitoring
    min_match_similarity: float = 0.6  # Minimum similarity score for market matching (0-1)
    dry_run_initial_balance: float = 10000.0
    simulate_fills: bool = True
    fill_probability: float = 0.8
    scan_interval_s: float = 10.0          # cross-platform scan cadence
    scan_max_pairs_per_cycle: int = 25     # caps order-book fetches per scan


@dataclass
class LoggingConfig:
    """Logging configuration."""
    console_level: str = "INFO"
    file_level: str = "DEBUG"
    log_dir: str = "logs"
    main_log_file: str = "bot.log"
    trades_log_file: str = "trades.log"
    opportunities_log_file: str = "opportunities.log"
    max_log_size_mb: int = 50
    backup_count: int = 5


@dataclass
class MonitoringConfig:
    """Monitoring configuration."""
    snapshot_interval: float = 60.0
    heartbeat_interval: float = 30.0
    track_latency: bool = True
    track_fill_rates: bool = True


@dataclass
class BotConfig:
    """Complete bot configuration."""
    api: ApiConfig = field(default_factory=ApiConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    mode: ModeConfig = field(default_factory=ModeConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    predictit: PredictItConfig = field(default_factory=PredictItConfig)
    
    @property
    def is_dry_run(self) -> bool:
        return self.mode.trading_mode.lower() == "dry_run"
    
    @property
    def is_live(self) -> bool:
        return self.mode.trading_mode.lower() == "live"
    
    @property
    def use_simulation(self) -> bool:
        """Use simulated data (for demos/screenshots)."""
        return self.mode.data_mode.lower() == "simulation"


def load_config(config_path: str = "config.yaml") -> BotConfig:
    """
    Load configuration from a YAML file.
    
    Args:
        config_path: Path to the configuration file
        
    Returns:
        BotConfig instance with loaded values
        
    Raises:
        ConfigError: If the config file cannot be loaded or is invalid
    """
    path = Path(config_path)
    
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {config_path}")
    
    try:
        with open(path, "r") as f:
            raw_config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in config file: {e}")
    
    if raw_config is None:
        raw_config = {}
    
    # Parse sections
    api_data = raw_config.get("api", {})
    trading_data = raw_config.get("trading", {})
    risk_data = raw_config.get("risk", {})
    mode_data = raw_config.get("mode", {})
    logging_data = raw_config.get("logging", {})
    monitoring_data = raw_config.get("monitoring", {})
    server_data = raw_config.get("server") or {}
    database_data = raw_config.get("database") or {}
    ai_data = raw_config.get("ai") or {}
    predictit_data = raw_config.get("predictit") or {}
    
    _warn_secrets_in_yaml(api_data, config_path)
    
    # Handle environment variable overrides
    api_data = _apply_env_overrides(api_data, _SECRET_ENV_MAP)
    database_data = _apply_env_overrides(database_data, {"url": "DATABASE_URL"})
    server_data = _extend_allowed_hosts(server_data)
    
    # Build config objects
    config = BotConfig(
        api=_build_dataclass(ApiConfig, api_data),
        trading=_build_dataclass(TradingConfig, trading_data),
        risk=_build_dataclass(RiskConfig, risk_data),
        mode=_build_dataclass(ModeConfig, mode_data),
        logging=_build_dataclass(LoggingConfig, logging_data),
        monitoring=_build_dataclass(MonitoringConfig, monitoring_data),
        server=_build_dataclass(ServerConfig, server_data),
        database=_build_dataclass(DatabaseConfig, database_data),
        ai=_build_dataclass(AIConfig, ai_data),
        predictit=_build_dataclass(PredictItConfig, predictit_data),
    )
    
    # Validate
    validate_config(config)
    
    return config


def _extend_allowed_hosts(server_data: dict) -> dict:
    """``MARKE_ALLOWED_HOSTS`` (comma-separated), and the hostname Render or Railway
    announces, add to the configured hosts.

    It extends rather than replaces, so loopback stays allowed for the
    container health check. Used for platforms that assign the hostname at deploy time.
    """
    extra = [h.strip() for h in os.environ.get("MARKE_ALLOWED_HOSTS", "").split(",") if h.strip()]
    # Hostnames announced by the hosting platform itself (Render, Railway)
    for var in ("RENDER_EXTERNAL_HOSTNAME", "RAILWAY_PUBLIC_DOMAIN"):
        value = os.environ.get(var, "").strip()
        if value:
            extra.append(value)
    if not extra:
        return server_data
    base = list(server_data.get("allowed_hosts") or ServerConfig().allowed_hosts)
    merged = base + [h for h in extra if h not in base]
    return {**server_data, "allowed_hosts": merged}


def _warn_secrets_in_yaml(api_data: dict, config_path: str) -> None:
    """Warn when real-looking credentials are stored in the YAML file."""
    for key in _SECRET_ENV_MAP:
        value = api_data.get(key)
        if value and not str(value).startswith("YOUR_"):
            logger.warning(
                "api.%s is set in %s. Storing credentials in the config file is "
                "deprecated; set %s in the environment or .env instead.",
                key, config_path, _SECRET_ENV_MAP[key],
            )


def _apply_env_overrides(data: dict, env_map: dict[str, str]) -> dict:
    """Apply environment variable overrides to config data."""
    result = data.copy()
    for key, env_var in env_map.items():
        env_value = os.environ.get(env_var)
        if env_value:
            result[key] = env_value
    return result


def _build_dataclass(cls, data: dict):
    """Build a dataclass from a dictionary, ignoring unknown keys."""
    import dataclasses
    
    field_names = {f.name for f in dataclasses.fields(cls)}
    filtered_data = {k: v for k, v in data.items() if k in field_names}
    return cls(**filtered_data)


def validate_config(config: BotConfig) -> None:
    """Validate configuration values (call again after CLI overrides)."""
    errors = []
    
    # Trading validation
    if config.trading.min_edge < 0 or config.trading.min_edge > 1:
        errors.append("trading.min_edge must be between 0 and 1")
    
    if config.trading.min_spread < 0 or config.trading.min_spread > 1:
        errors.append("trading.min_spread must be between 0 and 1")
    
    if config.trading.tick_size <= 0:
        errors.append("trading.tick_size must be positive")
    
    if config.trading.default_order_size <= 0:
        errors.append("trading.default_order_size must be positive")
    
    # Risk validation
    if config.risk.max_position_per_market <= 0:
        errors.append("risk.max_position_per_market must be positive")
    
    if config.risk.max_global_exposure <= 0:
        errors.append("risk.max_global_exposure must be positive")
    
    if config.risk.max_daily_loss < 0:
        errors.append("risk.max_daily_loss must be non-negative")
    
    if config.risk.max_drawdown_pct < 0 or config.risk.max_drawdown_pct > 1:
        errors.append("risk.max_drawdown_pct must be between 0 and 1")
    
    # Mode validation
    if config.mode.trading_mode.lower() not in ("live", "dry_run"):
        errors.append("mode.trading_mode must be 'live' or 'dry_run'")
    
    # Live trading is not implemented: order placement is an unsigned stub.
    if config.is_live:
        errors.append("live trading is disabled in this build (use dry_run)")
    
    # AI / server validation
    if not 0 <= config.ai.min_confidence <= 1 or not 0 <= config.ai.min_confidence_caveats <= 1:
        errors.append("ai.min_confidence and ai.min_confidence_caveats must be between 0 and 1")
    if config.ai.provider.lower() not in ("gemini", "anthropic", "mock"):
        errors.append("ai.provider must be one of: gemini, anthropic, mock")
    if not 0 <= config.ai.verifier_reserve_pct <= 100:
        errors.append("ai.verifier_reserve_pct must be between 0 and 100")
    if not 1 <= config.server.port <= 65535:
        errors.append("server.port must be a valid TCP port")
    
    if errors:
        raise ConfigError("Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))


def save_config(config: BotConfig, config_path: str = "config.yaml") -> None:
    """Save configuration to a YAML file."""
    import dataclasses
    
    def to_dict(obj):
        if dataclasses.is_dataclass(obj):
            return {k: to_dict(v) for k, v in dataclasses.asdict(obj).items()}
        return obj
    
    data = to_dict(config)
    
    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def get_default_config() -> BotConfig:
    """Get a default configuration."""
    return BotConfig()



# Backwards-compatible alias
_validate_config = validate_config
