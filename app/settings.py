"""Runtime settings the UI may change.

Whitelisted keys only, each with a type and range. ``trading_mode`` is
deliberately absent: it is read-only and cannot be changed from the web.
"""

from dataclasses import dataclass
from typing import Any, Optional

from app import repo


@dataclass(frozen=True)
class Setting:
    key: str
    kind: str                       # bool | float | int
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    label: str = ""


SETTINGS: dict[str, Setting] = {s.key: s for s in [
    Setting("ai.enabled", "bool", label="AI verification"),
    Setting("ai.min_confidence", "float", 0.0, 1.0, "Min confidence (identical)"),
    Setting("ai.min_confidence_caveats", "float", 0.0, 1.0, "Min confidence (with caveats)"),
    Setting("ai.daily_call_budget", "int", 0, 100000, "Daily call budget"),
    Setting("ai.daily_cost_budget_usd", "float", 0.0, 1000.0, "Daily cost budget (USD, 0 = none)"),
    Setting("mode.kalshi_enabled", "bool", label="Kalshi source"),
    Setting("predictit.enabled", "bool", label="PredictIt source"),
    Setting("trading.min_edge", "float", 0.0, 1.0, "Minimum net edge"),
]}


class SettingError(ValueError):
    pass


def coerce(key: str, value: Any) -> Any:
    spec = SETTINGS.get(key)
    if spec is None:
        raise SettingError(f"Setting '{key}' cannot be changed")
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise SettingError(f"{key} must be true or false")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SettingError(f"{key} must be a number")
    num = int(value) if spec.kind == "int" else float(value)
    if spec.kind == "int" and float(value) != num:
        raise SettingError(f"{key} must be a whole number")
    if (spec.minimum is not None and num < spec.minimum) or (
            spec.maximum is not None and num > spec.maximum):
        raise SettingError(f"{key} must be between {spec.minimum} and {spec.maximum}")
    return num


def _resolve(config, key: str):
    section, attr = key.split(".", 1)
    return getattr(config, section), attr


def get_value(config, key: str) -> Any:
    obj, attr = _resolve(config, key)
    return getattr(obj, attr)


def apply(config, key: str, value: Any) -> Any:
    """Validate and set on the live config object. Returns the coerced value."""
    value = coerce(key, value)
    obj, attr = _resolve(config, key)
    setattr(obj, attr, value)
    return value


def apply_overrides(config, db) -> dict[str, Any]:
    """Load persisted overrides at startup (unknown/invalid ones are ignored)."""
    with db.session() as s:
        stored = repo.get_overrides(s)
    applied = {}
    for key, value in stored.items():
        try:
            applied[key] = apply(config, key, value)
        except SettingError:
            continue
    return applied


def describe(config) -> dict:
    return {
        "settings": {k: get_value(config, k) for k in SETTINGS},
        "schema": {k: {"kind": s.kind, "min": s.minimum, "max": s.maximum, "label": s.label}
                   for k, s in SETTINGS.items()},
        "readonly": {
            "trading_mode": config.mode.trading_mode,
            "data_mode": config.mode.data_mode,
            "ai.provider": config.ai.provider,
            "ai.model": config.ai.model,
        },
    }
