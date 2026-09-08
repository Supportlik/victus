"""T-OPS-004: configuration precedence env > yaml > defaults."""

from pathlib import Path

import pytest

from victus.config.server import ServerConfig, load_server_config


def test_defaults() -> None:
    cfg = ServerConfig()
    assert cfg.database.url == "sqlite:///data/victus.db"
    assert cfg.agent.enabled is False
    assert cfg.mcp.allowed_cidrs == ["100.64.0.0/10"]


def test_yaml_overrides_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VICTUS_DATABASE__URL", raising=False)
    f = tmp_path / "victus.yaml"
    f.write_text("database:\n  url: sqlite:///x.db\nagent:\n  enabled: true\n", encoding="utf-8")
    cfg = load_server_config(f)
    assert cfg.database.url == "sqlite:///x.db"
    assert cfg.agent.enabled is True


def test_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "victus.yaml"
    f.write_text("database:\n  url: sqlite:///from-yaml.db\n", encoding="utf-8")
    monkeypatch.setenv("VICTUS_DATABASE__URL", "postgresql+psycopg://u:p@db/victus")
    cfg = load_server_config(f)
    assert cfg.database.url == "postgresql+psycopg://u:p@db/victus"


def test_missing_yaml_is_fine(tmp_path: Path) -> None:
    cfg = load_server_config(tmp_path / "nope.yaml")
    assert cfg.server.port == 8000


def test_secrets_are_masked() -> None:
    cfg = ServerConfig(providers={"openai_api_key": "sk-test"})  # type: ignore[arg-type]
    assert "sk-test" not in repr(cfg)
    assert cfg.providers.openai_api_key is not None
    assert cfg.providers.openai_api_key.get_secret_value() == "sk-test"
