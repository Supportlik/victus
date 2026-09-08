"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from victus.api.app import create_app
from victus.config.server import ServerConfig


@pytest.fixture
def config() -> ServerConfig:
    """A configuration that ignores victus.yaml and the environment."""
    return ServerConfig(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def client(config: ServerConfig) -> Iterator[TestClient]:
    with TestClient(create_app(config)) as c:
        yield c
