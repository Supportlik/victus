"""T-MCP-200…222: every tool handler of the registry against the database, through ``dispatch``.

Each test calls the tool the way an MCP client or the in-house worker does and asserts what
that caller reads back — the JSON, the error code — plus, where a tool writes, what a second
read shows. The scope matrix lives elsewhere; here the context holds every scope unless a
test narrows it to show the degraded path.
"""

from __future__ import annotations

import base64
import dataclasses
import enum
from datetime import date
from decimal import Decimal
from typing import Any, cast

import pytest
from pydantic import BaseModel

from victus.application.tenant_context import (
    SCOPE_AGENT_WRITE,
    SCOPE_CAPTURE_READ,
    SCOPE_READ,
    SCOPE_WRITE,
    TenantContext,
)
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases import recipes as recipe_uc
from victus.application.use_cases import settings as settings_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.transcription.fake import FakeTranscription
from victus.mcp import tools
from victus.mcp.tools import ImageResult, ToolContext, ToolError, dispatch

DAY = date(2026, 3, 10)
#: Illustrative tenant settings; rules live in the settings document, so one must exist.
SETTINGS: dict[str, Any] = {
    "goal": {"weight_kg": 80, "date": "2027-01-31"},
    "kcal_per_kg": 7716.17,
    "calorie_corridor": {"min": 1400, "max": 2000, "asymmetric": True},
    "target_bands": [
        {
            "name": "Rest day",
            "training_type": "rest",
            "valid_from": "2026-01-01",
            "protein": {"min": 105, "opt_min": 150, "opt_max": 185, "target": 165, "max": 200},
            "carbs": {"min": 120, "opt_min": 155, "opt_max": 200, "target": 180, "max": 230},
            "fat": {"min": 45, "opt_min": 55, "opt_max": 70, "target": 58, "max": 75},
            "fiber": {"min": 25, "opt_min": 32, "opt_max": 38, "target": 35, "max": 50},
            "salt": {"min": 4, "opt_min": 6, "opt_max": 8, "target": 8, "max": 15},
        }
    ],
}
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63f8ffff3f0300050001ff2b3a4c0000000049454e44ae426082"
)


def _with_scopes(tc: ToolContext, *scopes: str) -> ToolContext:
    ctx = dataclasses.replace(tc.ctx, token_id="tok_narrow", scopes=frozenset(scopes))
    return dataclasses.replace(tc, ctx=ctx)


def _d(value: Any) -> dict[str, Any]:
    assert isinstance(value, dict), value
    return cast(dict[str, Any], value)


def _l(value: Any) -> list[Any]:
    assert isinstance(value, list), value
    return cast(list[Any], value)


def _item(skyr: int, raw: str, quantity: float) -> dict[str, Any]:
    return {
        "raw_text": raw,
        "candidates": [],
        "chosen_consumable_id": skyr,
        "quantity": quantity,
        "unit_code": "g",
        "estimated": False,
        "quantity_estimated": False,
        "confidence": 0.9,
        "rationale": "Synthetic draft item.",
        "source_kind": "text",
        "source_capture_id": "cap_test",
    }


def _draft_day(tc: ToolContext, skyr: int, day: date = DAY) -> dict[str, Any]:
    """Draft ``day`` with two skyr items (100 g and 50 g) through the agent tools."""
    run = _d(dispatch(tc, "agent_run_start", {"mode": "manual", "dates": [day.isoformat()]}))
    written = _d(
        dispatch(
            tc,
            "draft_create",
            {
                "run_id": run["run_id"],
                "date": day.isoformat(),
                "source_captures": [],
                "meals": [
                    {
                        "name": "Breakfast",
                        "time": "08:00",
                        "line_items": [
                            _item(skyr, "a bowl of skyr", 100),
                            _item(skyr, "a spoon more", 50),
                        ],
                    }
                ],
            },
        )
    )
    dispatch(tc, "agent_run_finish", {"run_id": run["run_id"]})
    return _d(written["day"])


# ── body, weight, recipes, rules, usage ──────────────────────────────────────


@pytest.mark.covers("mcp:body_add", "mcp:body_measurements")
def test_t_mcp_200_body_add_then_body_measurements(tool_ctx: ToolContext) -> None:
    """T-MCP-200: a tape session is stored as given; the limit keeps the newest sessions."""
    added = _d(
        dispatch(
            tool_ctx,
            "body_add",
            {"measured_at": "2026-03-10T07:00:00+00:00", "waist_cm": 90.5, "note": "tape"},
        )
    )
    assert added["waist_cm"] == 90.5 and added["hip_cm"] is None and added["note"] == "tape"
    dispatch(tool_ctx, "body_add", {"measured_at": "2026-03-12T07:00:00+00:00", "hip_cm": 101})
    listed = _d(dispatch(tool_ctx, "body_measurements", {"limit": 5}))
    assert sorted(m["measured_at"][:10] for m in listed["measurements"]) == [
        "2026-03-10",
        "2026-03-12",
    ]
    newest = _d(dispatch(tool_ctx, "body_measurements", {"limit": 1}))["measurements"]
    assert [m["hip_cm"] for m in newest] == [101]


@pytest.mark.covers("mcp:weight_add")
def test_t_mcp_201_weight_add_records_a_manual_entry(tool_ctx: ToolContext) -> None:
    """T-MCP-201: a manual weight comes back with its value and the manual source."""
    entry = _d(dispatch(tool_ctx, "weight_add", {"measured_at": "2026-03-10T07:00:00", "kg": 80}))
    assert entry["kg"] == 80 and entry["source"] == "manual" and entry["id"]


@pytest.mark.covers("mcp:recipe_get")
def test_t_mcp_202_recipe_get_returns_ingredients(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-MCP-202: a recipe reads with its ingredients; an unknown id is NotFound."""
    recipe = recipe_uc.CreateRecipe(factory, alice).execute("Skyr bowl", default_servings=2)
    recipe_uc.SetIngredients(factory, alice).execute(
        recipe.id, [recipe_uc.IngredientInput(product_id=skyr, amount=200, unit_code="g")]
    )
    got = _d(dispatch(tool_ctx, "recipe_get", {"id": recipe.id}))
    assert got["name"] == "Skyr bowl" and got["default_servings"] == 2
    assert len(got["ingredients"]) == 1 and got["ingredients"][0]["product_id"] == skyr
    with pytest.raises(ToolError) as missing:
        dispatch(tool_ctx, "recipe_get", {"id": 999_999})
    assert missing.value.code == "NotFound"


@pytest.mark.covers("mcp:rule_upsert", "mcp:rules_list", "mcp:rule_delete")
def test_t_mcp_203_rules_upsert_list_delete(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext
) -> None:
    """T-MCP-203: a rule is written, filtered by scope, replaced by name and removed."""
    settings_uc.PutSettings(factory, alice).execute(dict(SETTINGS))
    written = _d(
        dispatch(
            tool_ctx,
            "rule_upsert",
            {
                "name": "rolls",
                "when": "bread rolls from the bakery",
                "then": "take the values from their own site",
                "scope": "products",
            },
        )
    )
    assert written["name"] == "rolls" and written["scope"] == "products"
    dispatch(tool_ctx, "rule_upsert", {"name": "days", "when": "a rest day", "then": "say so"})
    assert {r["name"] for r in _l(dispatch(tool_ctx, "rules_list", {}))} == {"rolls", "days"}
    products_only = _l(dispatch(tool_ctx, "rules_list", {"scope": "products"}))
    assert "rolls" in {r["name"] for r in products_only}
    assert all(r["scope"] in ("products", "all") for r in products_only)
    dispatch(tool_ctx, "rule_upsert", {"name": "rolls", "when": "rolls", "then": "ask first"})
    rows = {r["name"]: r for r in _l(dispatch(tool_ctx, "rules_list", {}))}
    assert rows["rolls"]["then"] == "ask first"
    assert dispatch(tool_ctx, "rule_delete", {"name": "rolls"}) == {"deleted": "rolls"}
    assert [r["name"] for r in _l(dispatch(tool_ctx, "rules_list", {}))] == ["days"]


@pytest.mark.covers("mcp:line_item_create", "mcp:product_usage")
def test_t_mcp_204_product_usage_lists_the_days_a_product_was_logged(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-MCP-204: product_usage names the day, meal and amount of every logged item."""
    day_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    dispatch(
        tool_ctx,
        "line_item_create",
        {"date": DAY.isoformat(), "meal": "Lunch", "consumable_id": skyr, "amount": 150},
    )
    usage = _d(dispatch(tool_ctx, "product_usage", {"product_id": skyr}))
    assert usage["product_id"] == skyr and usage["days"] == 1 and usage["item_count"] == 1
    entry = usage["entries"][0]
    assert (entry["date"], entry["meal"], entry["base_amount"]) == (DAY.isoformat(), "Lunch", 150)


# ── day thread, drafts, approval ─────────────────────────────────────────────


@pytest.mark.covers("mcp:day_message_add", "mcp:day_thread_get")
def test_t_mcp_205_day_message_add_then_day_thread_get(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext
) -> None:
    """T-MCP-205: a user message lands in the thread the drafting session reads."""
    day_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    msg = _d(dispatch(tool_ctx, "day_message_add", {"date": DAY.isoformat(), "text": "a banana"}))
    assert msg["role"] == "user" and msg["content"] == "a banana"
    thread = _d(dispatch(tool_ctx, "day_thread_get", {"date": DAY.isoformat()}))
    assert thread["date"] == DAY.isoformat() and thread["day"]["date"] == DAY.isoformat()
    assert [m["content"] for m in thread["thread"]] == ["a banana"]
    full = _d(
        dispatch(tool_ctx, "day_thread_get", {"date": DAY.isoformat(), "include_processed": True})
    )
    assert [m["content"] for m in full["thread"]] == ["a banana"]


@pytest.mark.covers(
    "mcp:agent_run_start",
    "mcp:draft_create",
    "mcp:agent_run_finish",
    "mcp:drafts_list",
    "mcp:draft_summary",
    "mcp:draft_discard",
)
def test_t_mcp_206_drafts_list_summary_and_discard(tool_ctx: ToolContext, skyr: int) -> None:
    """T-MCP-206: a drafted day is listed and summarised; discarding removes its items."""
    _draft_day(tool_ctx, skyr)
    listed = _l(dispatch(tool_ctx, "drafts_list", {}))
    assert [(d["date"], d["draft_items"]) for d in listed] == [(DAY.isoformat(), 2)]
    summary = _d(dispatch(tool_ctx, "draft_summary", {"date": DAY.isoformat()}))
    assert summary["date"] == DAY.isoformat() and "Skyr natural" in summary["markdown"]
    assert summary["day"]["status"] == "draft"
    gone = dispatch(tool_ctx, "draft_discard", {"date": DAY.isoformat()})
    assert gone == {"date": DAY.isoformat(), "discarded_items": 2}
    assert dispatch(tool_ctx, "drafts_list", {}) == []


@pytest.mark.covers("mcp:day_approve", "mcp:day_get")
def test_t_mcp_207_day_approve_applies_corrections(tool_ctx: ToolContext, skyr: int) -> None:
    """T-MCP-207: corrections change one item and delete the other before approval."""
    day = _draft_day(tool_ctx, skyr)
    first, second = day["meals"][0]["line_items"]
    approved = _d(
        dispatch(
            tool_ctx,
            "day_approve",
            {
                "date": DAY.isoformat(),
                "close": False,
                "corrections": [
                    {"line_item_id": first["id"], "amount": 200, "unit_code": "g"},
                    {"line_item_id": second["id"], "delete": True},
                ],
            },
        )
    )
    items = approved["meals"][0]["line_items"]
    assert [(i["id"], i["base_amount"], i["is_draft"]) for i in items] == [
        (first["id"], 200, False)
    ]
    assert approved["status"] == "open"
    assert _d(dispatch(tool_ctx, "day_get", {"date": DAY.isoformat()}))["status"] == "open"


@pytest.mark.covers("mcp:line_item_approve")
def test_t_mcp_208_line_item_approve_with_and_without_correction(
    tool_ctx: ToolContext, skyr: int
) -> None:
    """T-MCP-208: one item is accepted as is, the other corrected and moved to a new meal."""
    day = _draft_day(tool_ctx, skyr)
    first, second = day["meals"][0]["line_items"]
    plain = _d(dispatch(tool_ctx, "line_item_approve", {"line_item_id": first["id"]}))
    assert plain["is_draft"] is False and plain["base_amount"] == 100
    moved = _d(
        dispatch(
            tool_ctx,
            "line_item_approve",
            {"line_item_id": second["id"], "amount": 75, "meal_name": "Snack"},
        )
    )
    assert moved["is_draft"] is False and moved["base_amount"] == 75
    after = _d(dispatch(tool_ctx, "day_get", {"date": DAY.isoformat()}))
    assert {m["name"]: len(m["line_items"]) for m in after["meals"]} == {
        "Breakfast": 1,
        "Snack": 1,
    }
    with pytest.raises(ToolError) as again:
        dispatch(tool_ctx, "line_item_approve", {"line_item_id": first["id"]})
    assert again.value.code == "Conflict"


@pytest.mark.covers("mcp:line_item_create", "mcp:line_item_update", "mcp:line_item_delete")
def test_t_mcp_209_line_item_create_update_delete(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-MCP-209: a second item joins the existing meal; update and delete show on the day."""
    day_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    args = {"date": DAY.isoformat(), "consumable_id": skyr, "amount": 100}
    a = _d(dispatch(tool_ctx, "line_item_create", {**args, "meal": "Lunch"}))
    b = _d(dispatch(tool_ctx, "line_item_create", {**args, "meal": " lunch "}))
    assert a["meal_id"] == b["meal_id"], "the meal name is matched, not duplicated"
    updated = _d(
        dispatch(
            tool_ctx, "line_item_update", {"line_item_id": b["id"], "amount": 1, "unit_code": "tub"}
        )
    )
    assert updated["base_amount"] == 400
    assert dispatch(tool_ctx, "line_item_delete", {"line_item_id": a["id"]}) == {"deleted": a["id"]}
    day = _d(dispatch(tool_ctx, "day_get", {"date": DAY.isoformat()}))
    assert [i["id"] for m in day["meals"] for i in m["line_items"]] == [b["id"]]


@pytest.mark.covers("mcp:meal_update", "mcp:meal_delete")
def test_t_mcp_210_meal_update_and_delete(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext
) -> None:
    """T-MCP-210: a meal is renamed and timed, then deleted while empty."""
    day_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    meal = day_uc.AddMeal(factory, alice).execute(DAY, "Lunch")
    renamed = _d(
        dispatch(tool_ctx, "meal_update", {"meal_id": meal.id, "name": "Dinner", "time": "19:30"})
    )
    assert renamed["name"] == "Dinner" and renamed["time"] == "19:30:00"
    assert dispatch(tool_ctx, "meal_delete", {"meal_id": meal.id}) == {"deleted": meal.id}
    assert _d(dispatch(tool_ctx, "day_get", {"date": DAY.isoformat()}))["meals"] == []


# ── reports and snapshots ────────────────────────────────────────────────────


@pytest.mark.covers("mcp:report_render")
def test_t_mcp_211_report_render_periods_and_errors(tool_ctx: ToolContext) -> None:
    """T-MCP-211: explicit from/to is honoured; reversed dates, bad tokens and names fail."""
    data = _d(
        dispatch(
            tool_ctx,
            "report_render",
            {"format": "json", "from": "2026-03-01", "to": "2026-03-10", "as_of": "2026-03-10"},
        )
    )
    assert "blocks" in data
    md = dispatch(tool_ctx, "report_render", {"as_of": "2026-03-10"})
    assert isinstance(md, str) and md.startswith("#")
    cases = [
        ({"from": "2026-03-10", "to": "2026-03-01"}, "validation", "before"),
        ({"period": "fortnight"}, "validation", ""),
        ({"name": "no_such_report"}, "not_found", "no_such_report"),
    ]
    for args, code, text in cases:
        with pytest.raises(ToolError) as exc:
            dispatch(tool_ctx, "report_render", args)
        assert exc.value.code == code and text in exc.value.message


@pytest.mark.covers(
    "mcp:report_snapshot_create",
    "mcp:report_snapshots_list",
    "mcp:report_snapshot_get",
    "mcp:report_assess",
)
def test_t_mcp_212_snapshot_create_list_get_assess(tool_ctx: ToolContext) -> None:
    """T-MCP-212: snapshots freeze the asked period; one is assessed and read back."""
    explicit = _d(
        dispatch(
            tool_ctx,
            "report_snapshot_create",
            {"as_of": "2026-03-10", "start": "2026-03-01", "end": "2026-03-08", "label": "early"},
        )
    )
    assert (explicit["period_start"], explicit["period_end"]) == ("2026-03-01", "2026-03-08")
    assert explicit["result"]["from"] == "2026-03-01" and explicit["result"]["today"] == (
        "2026-03-10"
    )
    token = _d(
        dispatch(tool_ctx, "report_snapshot_create", {"as_of": "2026-03-10", "period": "7d"})
    )
    assert token["period_end"] == "2026-03-10" and token["period_start"] == "2026-03-04"
    default = _d(dispatch(tool_ctx, "report_snapshot_create", {"as_of": "2026-03-10"}))
    assert default["status"] == "frozen" and default["report_name"] == "checkup"

    listed = _l(dispatch(tool_ctx, "report_snapshots_list", {"report": "checkup", "limit": 2}))
    assert len(listed) == 2
    assert len(_l(dispatch(tool_ctx, "report_snapshots_list", {}))) == 3

    assessed = _d(
        dispatch(
            tool_ctx,
            "report_assess",
            {"snapshot_id": explicit["id"], "assessment_md": "Hold the current intake."},
        )
    )
    assert assessed["status"] == "assessed" and assessed["prompt_version"] == "external"
    got = _d(dispatch(tool_ctx, "report_snapshot_get", {"snapshot_id": explicit["id"]}))
    assert got["assessment_md"] == "Hold the current intake." and got["label"] == "early"


@pytest.mark.covers("mcp:report_snapshot_create", "mcp:report_assess")
def test_t_mcp_213_report_assess_without_a_config_records_no_model(
    tool_ctx: ToolContext,
) -> None:
    """T-MCP-213: a context without server config assesses with model None and the run's prompt."""
    snap = _d(dispatch(tool_ctx, "report_snapshot_create", {"as_of": "2026-03-10"}))
    bare = dataclasses.replace(tool_ctx, config=None, prompt_version="p-1")  # type: ignore[arg-type]
    assessed = _d(
        dispatch(bare, "report_assess", {"snapshot_id": snap["id"], "assessment_md": "Fine."})
    )
    assert assessed["model"] is None and assessed["prompt_version"] == "p-1"


# ── captures ─────────────────────────────────────────────────────────────────


@pytest.mark.covers("mcp:captures_open", "mcp:agent_run_start")
def test_t_mcp_214_captures_open_inside_a_run_sees_only_locked_days(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext
) -> None:
    """T-MCP-214: inside a run only the locked day's captures show, unless a date is named."""
    assert tool_ctx.blobs is not None
    upload = capture_uc.UploadCapture(factory, alice, tool_ctx.blobs)
    locked = upload.execute(capture_uc.UploadInput(text="breakfast skyr", target_date=DAY))
    other = upload.execute(capture_uc.UploadInput(text="dinner", target_date=date(2026, 3, 11)))
    run = _d(dispatch(tool_ctx, "agent_run_start", {"mode": "manual", "dates": [DAY.isoformat()]}))
    in_run = dataclasses.replace(tool_ctx, run_id=run["run_id"])
    assert [c["id"] for c in _l(dispatch(in_run, "captures_open", {}))] == [locked.id]
    named = _l(dispatch(in_run, "captures_open", {"date": "2026-03-11"}))
    assert [c["id"] for c in named] == [other.id]
    unknown_run = dataclasses.replace(tool_ctx, run_id="run_missing")
    assert dispatch(unknown_run, "captures_open", {}) == [], "an unknown run locks nothing"


@pytest.mark.covers("mcp:capture_get")
def test_t_mcp_215_capture_get_transcribes_audio_on_demand(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext
) -> None:
    """T-MCP-215: an audio capture without transcript is transcribed when it is read."""
    assert tool_ctx.blobs is not None
    cap = capture_uc.UploadCapture(factory, alice, tool_ctx.blobs).execute(
        capture_uc.UploadInput(
            data=b"RIFF....WAVEfake", filename="note.wav", mime="audio/wav", target_date=DAY
        )
    )
    fake = FakeTranscription("two slices of rye bread")
    with_stt = dataclasses.replace(tool_ctx, transcription=fake)
    got = _d(dispatch(with_stt, "capture_get", {"id": cap.id}))
    assert got["transcript"] == "two slices of rye bread" and len(fake.calls) == 1

    fresh = capture_uc.UploadCapture(factory, alice, tool_ctx.blobs).execute(
        capture_uc.UploadInput(
            data=b"RIFF....WAVEother", filename="n2.wav", mime="audio/wav", target_date=DAY
        )
    )
    no_blobs = dataclasses.replace(with_stt, blobs=None)
    with pytest.raises(ToolError) as exc:
        dispatch(no_blobs, "capture_get", {"id": fresh.id})
    assert exc.value.code == "unavailable"


@pytest.mark.covers("mcp:capture_get")
def test_t_mcp_216_capture_get_text_image_and_attachment_choice(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext
) -> None:
    """T-MCP-216: text reads as JSON; an image returns the asked attachment or needs storage."""
    assert tool_ctx.blobs is not None
    upload = capture_uc.UploadCapture(factory, alice, tool_ctx.blobs)
    text = upload.execute(capture_uc.UploadInput(text="an apple", target_date=DAY))
    got = _d(dispatch(tool_ctx, "capture_get", {"id": text.id}))
    assert got["text"] == "an apple" and got["kind"] == "text"

    two = upload.execute(
        capture_uc.UploadInput(
            target_date=DAY,
            files=(
                capture_uc.UploadFile(PNG, "a.png", "image/png"),
                capture_uc.UploadFile(PNG + b"\x00", "b.png", "image/png"),
            ),
        )
    )
    second = two.attachments[1].id
    img = dispatch(tool_ctx, "capture_get", {"id": two.id, "attachment_id": second})
    assert isinstance(img, ImageResult) and img.mime == "image/png"
    assert base64.b64decode(img.data_b64) == PNG + b"\x00"

    with pytest.raises(ToolError) as exc:
        dispatch(dataclasses.replace(tool_ctx, blobs=None), "capture_get", {"id": two.id})
    assert exc.value.code == "unavailable"


@pytest.mark.covers("mcp:capture_get")
def test_t_mcp_217_capture_get_falls_back_to_the_single_image_attachment(
    tool_ctx: ToolContext,
    factory: UowFactory,
    alice: TenantContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-MCP-217: an image capture listing no attachments still returns its one image."""
    assert tool_ctx.blobs is not None
    cap = capture_uc.UploadCapture(factory, alice, tool_ctx.blobs).execute(
        capture_uc.UploadInput(data=PNG, filename="l.png", mime="image/png", target_date=DAY)
    )
    original = capture_uc.GetCapture.execute

    def without_list(self: capture_uc.GetCapture, capture_id: str) -> Any:
        return dataclasses.replace(original(self, capture_id), attachments=[])

    monkeypatch.setattr(capture_uc.GetCapture, "execute", without_list)
    img = dispatch(tool_ctx, "capture_get", {"id": cap.id})
    assert isinstance(img, ImageResult) and base64.b64decode(img.data_b64) == PNG


@pytest.mark.covers("mcp:capture_mark")
def test_t_mcp_218_capture_mark_sets_day_and_product(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-MCP-218: only the fields given change; a day and a product can be assigned."""
    assert tool_ctx.blobs is not None
    cap = capture_uc.UploadCapture(factory, alice, tool_ctx.blobs).execute(
        capture_uc.UploadInput(text="undated note")
    )
    dated = _d(dispatch(tool_ctx, "capture_mark", {"id": cap.id, "target_date": "2026-03-10"}))
    assert dated["target_date"] == "2026-03-10" and dated["status"] == "new"
    linked = _d(
        dispatch(tool_ctx, "capture_mark", {"id": cap.id, "product_id": skyr, "target_date": None})
    )
    assert linked["product_id"] == skyr and linked["target_date"] is None


# ── products ─────────────────────────────────────────────────────────────────


@pytest.mark.covers("mcp:product_update", "mcp:product_create", "mcp:product_get")
def test_t_mcp_219_product_update_proposes_and_product_create_applies(
    tool_ctx: ToolContext, skyr: int
) -> None:
    """T-MCP-219: without approve an update is a proposal; with it a product is created."""
    writer = _with_scopes(tool_ctx, SCOPE_READ, SCOPE_WRITE)
    proposed = _d(
        dispatch(writer, "product_update", {"product_id": skyr, "kcal": 70, "source": "label"})
    )
    assert proposed["pending_review"] is True and proposed["status"] == "pending"
    assert _d(dispatch(tool_ctx, "product_get", {"id": skyr}))["kcal"] == 63

    created = _d(dispatch(tool_ctx, "product_create", {"name": "Rye bread", "kcal": 220}))
    assert "pending_review" not in created and created["name"] == "Rye bread"
    assert _d(dispatch(tool_ctx, "product_get", {"id": created["id"]}))["kcal"] == 220


# ── dispatch error mapping and serialisation ─────────────────────────────────


@pytest.mark.covers("mcp:day_thread_get", "mcp:draft_create")
def test_t_mcp_220_dispatch_maps_use_case_errors(tool_ctx: ToolContext) -> None:
    """T-MCP-220: a scope the use case demands is `forbidden`; schema errors carry details."""
    reader = _with_scopes(tool_ctx, SCOPE_READ)
    with pytest.raises(ToolError) as scope:
        dispatch(reader, "day_thread_get", {"date": DAY.isoformat()})
    assert scope.value.code == "forbidden" and SCOPE_CAPTURE_READ in scope.value.message

    agent = _with_scopes(tool_ctx, SCOPE_READ, SCOPE_AGENT_WRITE)
    run = _d(dispatch(agent, "agent_run_start", {"mode": "manual", "dates": [DAY.isoformat()]}))
    with pytest.raises(ToolError) as invalid:
        dispatch(
            agent,
            "draft_create",
            {
                "run_id": run["run_id"],
                "date": DAY.isoformat(),
                "source_captures": [],
                "meals": [{}],
            },
        )
    assert invalid.value.code == "ValidationFailed", invalid.value.code
    assert "(" in invalid.value.message and "name" in invalid.value.message


def test_t_mcp_221_jsonable_covers_every_value_kind() -> None:
    """T-MCP-221: decimals, bytes, models, plain enums, non-string keys and others serialise."""

    class Colour(enum.Enum):
        RED = 1

    class Model(BaseModel):
        on: date

    class Opaque:
        def __str__(self) -> str:
            return "opaque"

    value = {
        1: Decimal("1.5"),
        "b": b"\x00\x01",
        "m": Model(on=DAY),
        "e": Colour.RED,
        "o": Opaque(),
        "t": (1, 2),
    }
    assert tools.jsonable(value) == {
        "1": 1.5,
        "b": "AAE=",
        "m": {"on": "2026-03-10"},
        "e": 1,
        "o": "opaque",
        "t": [1, 2],
    }


def test_t_mcp_222_strictify_skips_non_schema_entries() -> None:
    """T-MCP-222: boolean sub-schemas in properties and anyOf are left alone, objects tightened."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"free": True, "nested": {"type": "object", "properties": {}}},
        "anyOf": [True, {"type": "object", "properties": {"x": {"type": "string"}}}],
        "items": {"type": "object"},
    }
    tools._strictify(schema)
    assert schema["required"] == ["free", "nested"] and schema["additionalProperties"] is False
    assert schema["properties"]["free"] is True
    assert schema["properties"]["nested"]["additionalProperties"] is False
    assert schema["anyOf"][0] is True and schema["anyOf"][1]["required"] == ["x"]
    assert schema["items"]["additionalProperties"] is False
