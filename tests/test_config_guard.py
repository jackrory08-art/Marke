import logging

import pytest
import yaml

from utils.config_loader import ConfigError, load_config, validate_config


def write(tmp_path, data):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(data))
    return str(p)


def test_live_mode_rejected(tmp_path):
    with pytest.raises(ConfigError, match="live trading is disabled in this build"):
        load_config(write(tmp_path, {"mode": {"trading_mode": "live"}}))


def test_live_override_after_load_rejected(tmp_path):
    cfg = load_config(write(tmp_path, {}))
    cfg.mode.trading_mode = "live"  # what --live does
    with pytest.raises(ConfigError, match="live trading is disabled"):
        validate_config(cfg)


def test_secrets_in_yaml_warn(tmp_path, caplog):
    path = write(tmp_path, {"api": {"api_key": "real-looking-key", "private_key": "0xabc"}})
    with caplog.at_level(logging.WARNING):
        load_config(path)
    assert "api.api_key" in caplog.text and "POLYMARKET_API_KEY" in caplog.text
    assert "real-looking-key" not in caplog.text


def test_placeholders_do_not_warn(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        load_config(write(tmp_path, {"api": {"api_key": "YOUR_API_KEY_HERE"}}))
    assert "deprecated" not in caplog.text


def test_env_overrides_secrets_and_db(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYMARKET_API_KEY", "from-env")
    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/x.db")
    cfg = load_config(write(tmp_path, {}))
    assert cfg.api.api_key == "from-env"
    assert cfg.database.url == "sqlite:////tmp/x.db"


def test_old_config_without_new_sections_loads(tmp_path):
    cfg = load_config(write(tmp_path, {"trading": {"min_edge": 0.02}}))
    assert cfg.server.host == "127.0.0.1" and cfg.ai.model == "gemini-3.1-flash-lite"
    assert cfg.predictit.enabled is False


def test_shipped_config_has_no_secrets():
    text = open("config.yaml").read()
    assert "YOUR_API_KEY_HERE" not in text and "YOUR_PRIVATE_KEY_HERE" not in text
