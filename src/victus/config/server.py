"""Server configuration.

Precedence (highest first): environment variables ``VICTUS_*`` (nested keys
joined with ``__``, e.g. ``VICTUS_DATABASE__URL``) → ``victus.yaml`` (path from
``VICTUS_CONFIG``, default ``./victus.yaml``) → defaults below.

The full reference lives in ``docs/CONFIGURATION.md``; the JSON Schema in
``schemas/victus-server-config.schema.json`` describes the YAML file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class DatabaseConfig(BaseModel):
    url: str = "sqlite:///data/victus.db"
    echo: bool = False


class StorageConfig(BaseModel):
    backend: str = "fs"
    path: Path = Path("data/blobs")


class AuthConfig(BaseModel):
    rp_id: str | None = None
    rp_name: str = "Victus"
    origin: str | None = None
    session_ttl_days: int = 30


class ProvidersConfig(BaseModel):
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None


class TranscriptionConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o-transcribe"
    max_file_mb: int = 25
    ffmpeg_path: str = "ffmpeg"


class AgentBudget(BaseModel):
    max_input_tokens: int = 400_000
    max_output_tokens: int = 40_000
    max_usd_per_run: float = 2.0
    max_images_per_run: int = 12


class AgentConfig(BaseModel):
    enabled: bool = False
    # None disables the schedule; runs then start only on demand (API button, MCP).
    cron: str | None = "0 * * * *"
    # A single day is drafted well within this; a crashed run frees its day quickly.
    lock_ttl_minutes: int = 5
    model: str = "claude-sonnet-5"
    budget: AgentBudget = Field(default_factory=AgentBudget)


class McpConfig(BaseModel):
    http_enabled: bool = False
    # Tailscale's CGNAT range; the sensible default for a private mesh.
    allowed_cidrs: list[str] = Field(default_factory=lambda: ["100.64.0.0/10"])
    rate_limit_per_minute: int = 120


class BackupRetention(BaseModel):
    daily: int = 7
    weekly: int = 8
    monthly: int = 12


class BackupConfig(BaseModel):
    path: Path = Path("/backups")
    cron: str = "0 3 * * *"
    retention: BackupRetention = Field(default_factory=BackupRetention)


class ServerSection(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "info"


class ServerConfig(BaseSettings):
    """Process-wide configuration; see module docstring for precedence."""

    model_config = SettingsConfigDict(
        env_prefix="VICTUS_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    server: ServerSection = Field(default_factory=ServerSection)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # ``load_server_config`` passes the YAML document as init kwargs. By
        # default pydantic-settings lets init kwargs win over the environment;
        # we want the opposite (env > yaml > defaults), so env comes first.
        return (env_settings, dotenv_settings, init_settings, file_secret_settings)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


def load_server_config(config_file: Path | None = None) -> ServerConfig:
    """Load config with env > yaml > defaults precedence."""
    path = config_file or Path(os.environ.get("VICTUS_CONFIG", "victus.yaml"))
    return ServerConfig(**_read_yaml(path))
