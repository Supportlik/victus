"""Shared fixtures for the API smoke tests: an app on an in-memory database."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from victus.api.app import create_app
from victus.config.server import ServerConfig
from victus.infrastructure.migrations import runner


@pytest.fixture
def config(tmp_path: Path) -> ServerConfig:
    """A configuration that ignores victus.yaml and the environment."""
    return ServerConfig(  # type: ignore[call-arg]
        _env_file=None,
        database={"url": "sqlite://"},
        storage={"path": str(tmp_path / "blobs")},
        auth={"rp_id": "localhost", "origin": "http://localhost"},
    )


@pytest.fixture
def app(config: ServerConfig) -> Iterator[FastAPI]:
    application = create_app(config)
    runner.upgrade(engine=application.state.engine)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
