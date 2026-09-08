"""T-API-001/002: system endpoints."""

import pytest
from fastapi.testclient import TestClient

from victus import __version__

pytestmark = pytest.mark.api


def test_health(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["checks"]["process"] == "ok"


def test_version(client: TestClient) -> None:
    r = client.get("/api/v1/version")
    assert r.status_code == 200
    assert r.json() == {"version": __version__}


def test_openapi_is_served_under_api_prefix(client: TestClient) -> None:
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["title"] == "Victus"
