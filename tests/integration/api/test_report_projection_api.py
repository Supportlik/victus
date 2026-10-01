"""T-API-250 / T-API-251: the burndown's pace projections over HTTP and through MCP."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

pytestmark = pytest.mark.api

FIRST = date(2026, 8, 1)
AS_OF = date(2026, 9, 12)  # three days after the last weigh-in


def _weights() -> dict[date, float]:
    """Synthetic: thirty days down 0.12 kg a day, then ten days up — both kinds of window."""
    out = {FIRST + timedelta(days=i): round(92.0 - 0.12 * i, 2) for i in range(30)}
    out.update({FIRST + timedelta(days=30 + i): round(88.4 + 0.08 * i, 2) for i in range(10)})
    return out


def _seed(client: TestClient, token: dict[str, str]) -> None:
    doc = yaml.safe_load(
        (Path(__file__).parents[3] / "examples" / "tenant-settings.yaml").read_text("utf-8")
    )
    r = client.put("/api/v1/settings", json={"data": doc}, headers=token)
    assert r.status_code == 200, r.text
    for day, kg in _weights().items():
        r = client.post(
            "/api/v1/weight", json={"measured_at": f"{day}T07:00:00Z", "kg": kg}, headers=token
        )
        assert r.status_code == 201, r.text


def _block(payload: dict[str, Any], kind: str) -> dict[str, Any]:
    block = next(b for b in payload["blocks"] if b["meta"]["type"] == kind)
    assert not block["error"], block
    return block


def test_t_api_250_checkup_json_and_markdown(
    client: TestClient, alice_token: dict[str, str]
) -> None:
    """T-API-250: the check-up carries a projection per default window, each on the forecast ETA."""
    _seed(client, alice_token)
    r = client.get(f"/api/v1/reports/checkup?as_of={AS_OF}", headers=alice_token)
    assert r.status_code == 200, r.text
    payload = r.json()
    eta = {row["window"]: row["eta"] for row in _block(payload, "forecast")["rows"]}
    projections = _block(payload, "burndown")["result"]["projections"]
    assert [p["window"] for p in projections] == [7, 14, 30]
    for p in projections:
        assert p["crossing"] == eta[p["window"]]
    seven = projections[0]
    assert seven["crossing"] is None and seven["path"] == []  # rising at the end
    reaching = [p for p in projections if p["crossing"]]
    assert reaching, "the 30-day window still falls"
    for p in reaching:
        assert p["path"][0][0] == AS_OF.isoformat()
        assert p["days_vs_goal"] == (date.fromisoformat(p["crossing"]) - date(2027, 3, 31)).days
        assert [s["name"] for s in p["stages"]] == ["Stretch", "Target", "Minimum"]

    md = client.get(f"/api/v1/reports/checkup?as_of={AS_OF}&format=markdown", headers=alice_token)
    assert md.status_code == 200
    assert "| Pace | kg/wk | Reaches zero | vs. goal |" in md.text
    assert "| 7-day trend |" in md.text and "not at this pace" in md.text
    assert reaching[0]["crossing"] in md.text


def test_t_api_251_mcp_report_render(
    client: TestClient, alice_token: dict[str, str], alice_account: Any, api_app: Any
) -> None:
    """T-API-251: ``report_render`` over MCP shows the same pace table and the same days."""
    from victus.application.tenant_context import ALL_SCOPES, TenantContext
    from victus.mcp.server import make_tool_context
    from victus.mcp.tools import dispatch

    _seed(client, alice_token)
    tenant_id = alice_account.tenant_id
    state = api_app.state
    tc = make_tool_context(
        state.session_factory,
        TenantContext(tenant_id=tenant_id, scopes=ALL_SCOPES),
        state.config,
        blobs=None,
        transcription=None,
    )
    data = dispatch(tc, "report_render", {"format": "json", "as_of": AS_OF.isoformat()})
    assert isinstance(data, dict)
    http = client.get(f"/api/v1/reports/checkup?as_of={AS_OF}", headers=alice_token).json()
    assert (
        _block(data, "burndown")["result"]["projections"]
        == _block(http, "burndown")["result"]["projections"]
    )
    md = dispatch(tc, "report_render", {"as_of": AS_OF.isoformat()})
    assert isinstance(md, str)
    assert "| Pace | kg/wk | Reaches zero |" in md and "not at this pace" in md
