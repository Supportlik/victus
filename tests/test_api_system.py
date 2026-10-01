"""T-API-001/002: system endpoints."""

import pytest
from fastapi.testclient import TestClient

from victus import __version__

pytestmark = pytest.mark.api


@pytest.mark.covers("GET /api/v1/health")
def test_health(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    # no backup was ever recorded on this fresh database (T-API-150)
    assert body["status"] == "degraded" and body["checks"]["backup"] == "degraded"
    assert body["version"] == __version__
    assert body["checks"]["process"] == "ok"


@pytest.mark.covers("GET /api/v1/version")
def test_version(client: TestClient) -> None:
    r = client.get("/api/v1/version")
    assert r.status_code == 200
    assert r.json() == {"version": __version__}


def test_openapi_is_served_under_api_prefix(client: TestClient) -> None:
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["title"] == "Victus"
