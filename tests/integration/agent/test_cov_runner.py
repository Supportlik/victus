"""T-AGT-106…117: the runner's and the worker's paths the end-to-end tests do not walk.

Each case drives the worker with a scripted model (or one that fails on purpose) and checks
what the run records: outcome, status, summary, and what the model was sent.
"""

from __future__ import annotations

import io
import signal
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from PIL import Image
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from victus.agent import runner as runner_mod
from victus.agent import worker as worker_mod
from victus.agent.model import ModelError, ScriptedModelClient, ScriptedTurn
from victus.agent.worker import Worker
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import agent as agent_uc
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases import rules as rules_uc
from victus.application.use_cases import settings as settings_uc
from victus.application.use_cases import snapshots as snap_uc
from victus.application.use_cases._base import UowFactory
from victus.config.server import ServerConfig
from victus.infrastructure.db import orm
from victus.infrastructure.storage.memory import InMemoryBlobStorage
from victus.infrastructure.transcription.fake import FakeTranscription

from .conftest import DAY

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


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 180, 90)).save(buf, format="PNG")
    return buf.getvalue()


class FailingModel:
    """A model whose every call fails, the way an exhausted API key does."""

    model = "failing-model"

    def __init__(self) -> None:
        self.calls = 0

    def create(self, **_kw: Any) -> Any:
        self.calls += 1
        raise ModelError("upstream said no")


def _worker(
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    blobs: InMemoryBlobStorage,
    model: Any,
    tmp_path: Any,
    transcription: Any = None,
) -> Worker:
    return Worker(
        config,
        session_factory,
        model_factory=lambda _cfg: model,
        blobs=blobs,
        transcription=transcription,
        heartbeat_path=tmp_path / "alive",
    )


def _rules(factory: UowFactory, ctx: TenantContext) -> None:
    settings_uc.PutSettings(factory, ctx).execute(SETTINGS)
    for scope in ("days", "products", "reports"):
        rules_uc.UpsertRule(factory, ctx).execute(
            rules_uc.RuleInput(when=f"{scope} rule", then="say so", scope=scope)
        )


def _texts(content: Any) -> str:
    return "\n".join(str(block.get("text", "")) for block in content if isinstance(block, dict))


def test_t_agt_106_downscale_shrinks_converts_and_passes_failures_through() -> None:
    """T-AGT-106: a wide image is shrunk to the edge limit as JPEG, a small one is only
    converted, and bytes that are no image come back unchanged."""
    big, mime = runner_mod._downscale(_png(2000, 100), "image/png")
    assert mime == "image/jpeg"
    with Image.open(io.BytesIO(big)) as img:
        assert max(img.size) == runner_mod.MAX_IMAGE_EDGE
    small, mime = runner_mod._downscale(_png(10, 10), "image/png")
    assert mime == "image/jpeg" and small[:2] == b"\xff\xd8"
    assert runner_mod._downscale(b"not an image", "image/png") == (b"not an image", "image/png")


def test_t_agt_107_day_session_sees_rules_notes_images_and_tool_errors(
    factory: UowFactory,
    alice: TenantContext,
    skyr: int,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-107: the first message carries the tenant's day rules, a note for a recording
    that failed to transcribe, the images within budget and a line for the ones left out;
    a refused tool call goes back as an error result, and an image tool answers with an
    image block."""
    _rules(factory, alice)
    config.agent.budget.max_images_per_run = 1
    photos = capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(
            target_date=DAY,
            files=(
                capture_uc.UploadFile(_png(20, 20), "a.png", "image/png"),
                capture_uc.UploadFile(_png(30, 30), "b.png", "image/png"),
            ),
        )
    )
    capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(
            data=b"OggS-voice", filename="v.oga", mime="audio/ogg", target_date=DAY
        )
    )
    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    model = ScriptedModelClient(
        turns=[
            ScriptedTurn(
                tool_calls=[("product_get", {"id": 999_999}), ("capture_get", {"id": photos.id})]
            ),
            ScriptedTurn(text="Nothing to draft."),
        ]
    )
    worker = _worker(
        config, session_factory, blobs, model, tmp_path, transcription=FakeTranscription(fail=True)
    )

    outcomes = worker.run_once()

    assert outcomes[0].run.status == "finished"
    first = model.calls[0]["messages"][0]["content"]
    text = _texts(first)
    assert "days rule" in text and "products rule" not in text
    assert "transcription failed" in text
    assert "1 image(s) omitted" in text
    assert sum(1 for b in first if b.get("type") == "image") == 1
    results = model.calls[1]["messages"][-1]["content"]
    errors = [r for r in results if r.get("is_error")]
    assert len(errors) == 1
    image_result = next(r for r in results if not r.get("is_error"))
    assert any(part.get("type") == "image" for part in image_result["content"])


def test_t_agt_108_a_product_capture_is_reviewed_and_proposed(
    factory: UowFactory,
    alice: TenantContext,
    skyr: int,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-108: a capture about a product gets its own session with the product, the
    capture, the product rules and its label photo; a proposal from it is listed in the run
    summary, and with the image budget spent the photo is named as left out."""
    _rules(factory, alice)
    cap = capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(
            text="new label",
            product_id=skyr,
            data=_png(40, 40),
            filename="label.png",
            mime="image/png",
        )
    )
    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    model = ScriptedModelClient(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    (
                        "product_propose",
                        {"product_id": skyr, "changes": {"kcal": 64}, "capture_id": cap.id},
                    )
                ]
            ),
            ScriptedTurn(text="Proposed kcal 64."),
        ]
    )
    outcome = _worker(config, session_factory, blobs, model, tmp_path).run_once()[0]

    first = model.calls[0]["messages"][0]["content"]
    assert "products rule" in _texts(first)
    assert any(b.get("type") == "image" for b in first)
    assert outcome.summary_md is not None and "### Products" in outcome.summary_md
    assert "1 proposal(s) from 1 capture(s)" in outcome.summary_md
    assert "approve in the app" in outcome.summary_md

    # the image budget spent: the photo is named as left out
    config.agent.budget.max_images_per_run = 0
    cap2 = capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(
            text="back label",
            product_id=skyr,
            data=_png(41, 41),
            filename="b.png",
            mime="image/png",
        )
    )
    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    quiet = ScriptedModelClient(turns=[ScriptedTurn(text="Nothing to change.")])
    second = _worker(config, session_factory, blobs, quiet, tmp_path).run_once()[0]
    assert "omitted" in _texts(quiet.calls[0]["messages"][0]["content"])
    assert second.summary_md is not None and "product skipped" in second.summary_md
    assert cap2.id


def test_t_agt_109_a_product_capture_for_a_gone_product_fails_alone(
    factory: UowFactory,
    alice: TenantContext,
    skyr: int,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-AGT-109: a product capture whose session cannot start is a failed line in the
    summary; one that crashes is caught and recorded the same way; the run still finishes."""
    capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(text="label", product_id=skyr)
    )
    agent_uc.QueueAgentRun(factory, alice).execute("historical")

    def gone(*_a: Any, **_k: Any) -> Any:
        from victus.application.errors import NotFound

        raise NotFound("product gone")

    monkeypatch.setattr(runner_mod.product_uc.GetProduct, "execute", gone)
    model = ScriptedModelClient(turns=[])
    outcome = _worker(config, session_factory, blobs, model, tmp_path).run_once()[0]
    assert outcome.run.status == "finished"
    assert "failed: product gone" in (outcome.summary_md or "")
    assert model.calls == []

    def crash(self: Any, run_id: str, cap: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(runner_mod.DayDrafter, "run_product_capture", crash)
    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    again = _worker(config, session_factory, blobs, model, tmp_path).run_once()[0]
    assert "failed: boom" in (again.summary_md or "")


def test_t_agt_110_model_errors_and_stuck_sessions(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-110: a model that fails turns every day into ``failed`` and the run with it;
    a session that keeps calling tools past the turn limit is ``stuck``."""
    capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(text="lunch: skyr", target_date=DAY)
    )
    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    failing = FailingModel()
    outcome = _worker(config, session_factory, blobs, failing, tmp_path).run_once()[0]
    assert outcome.run.status == "failed"
    assert [d.outcome for d in outcome.days] == ["failed"]
    assert "upstream said no" in (outcome.run.error or "")

    config.agent.max_turns_per_day = 1
    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    looping = ScriptedModelClient(turns=[ScriptedTurn(tool_calls=[("product_search", {"q": "x"})])])
    stuck = _worker(config, session_factory, blobs, looping, tmp_path).run_once()[0]
    assert [d.outcome for d in stuck.days] == ["stuck"]
    assert "no result after 1 turns" in (stuck.days[0].error or "")


def test_t_agt_111_a_day_that_crashes_or_cannot_start(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-AGT-111: a day whose context cannot be read fails with the reason; a day whose
    session raises is caught; both release their lock."""
    from victus.application.errors import NotFound

    capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(text="tea", target_date=DAY)
    )
    agent_uc.QueueAgentRun(factory, alice).execute("historical")

    def unreadable(*_a: Any, **_k: Any) -> Any:
        raise NotFound("day context unreadable")

    monkeypatch.setattr(runner_mod.DayDrafter, "_first_message", unreadable)
    model = ScriptedModelClient(turns=[])
    first = _worker(config, session_factory, blobs, model, tmp_path).run_once()[0]
    assert first.days[0].outcome == "failed" and "unreadable" in (first.days[0].error or "")

    def crash(self: Any, run_id: str, day: date) -> Any:
        raise RuntimeError("kaput")

    monkeypatch.setattr(runner_mod.DayDrafter, "run_day", crash)
    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    second = _worker(config, session_factory, blobs, model, tmp_path).run_once()[0]
    assert second.days[0].error == "kaput"
    assert agent_uc.ListAgentLocks(factory, alice).execute() == []


def test_t_agt_112_a_spent_budget_skips_the_remaining_work(
    factory: UowFactory,
    alice: TenantContext,
    skyr: int,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-112: once the budget is spent, further product captures and days are skipped
    and the run ends ``budget_exceeded``."""
    config.agent.budget.max_output_tokens = 100
    for text in ("label one", "label two"):
        capture_uc.UploadCapture(factory, alice, blobs).execute(
            capture_uc.UploadInput(text=text, product_id=skyr)
        )
    for day in (DAY, DAY + timedelta(days=1)):
        capture_uc.UploadCapture(factory, alice, blobs).execute(
            capture_uc.UploadInput(text=f"meal on {day}", target_date=day)
        )
    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    model = ScriptedModelClient(turns=[ScriptedTurn(text="Looked.")])
    outcome = _worker(config, session_factory, blobs, model, tmp_path).run_once()[0]
    assert outcome.run.status == "budget_exceeded"
    assert len(model.calls) == 1
    assert set(outcome.skipped.values()) == {"budget exhausted"}


def test_t_agt_113_assessment_failures_and_budget(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-AGT-113: an assess run sees the report rules; a model that fails makes the run
    ``failed`` with the reason per snapshot; a crash is caught; a spent budget stops before
    the next snapshot and ends ``budget_exceeded``."""
    _rules(factory, alice)
    for label in ("first", "second"):
        snap_uc.FreezeReport(factory, alice).execute(
            "checkup",
            "Check-up",
            {"blocks": []},
            period_start=date(2026, 3, 1),
            period_end=DAY,
            today=DAY,
            label=label,
        )
    agent_uc.QueueAgentRun(factory, alice).execute("assess")
    failing = FailingModel()
    failed = _worker(config, session_factory, blobs, failing, tmp_path).run_once()[0]
    assert failed.run.status == "failed"
    assert "first (2026-03-10): upstream said no" in (failed.summary_md or "")

    config.agent.budget.max_output_tokens = 100
    agent_uc.QueueAgentRun(factory, alice).execute("assess")
    model = ScriptedModelClient(turns=[ScriptedTurn(text="Not yet.")])
    spent = _worker(config, session_factory, blobs, model, tmp_path).run_once()[0]
    assert spent.run.status == "budget_exceeded"
    assert "reports rule" in _texts(model.calls[0]["messages"][0]["content"])
    assert len(model.calls) == 1

    config.agent.budget.max_output_tokens = 40_000

    def crash(self: Any, run_id: str, snap: Any) -> Any:
        raise RuntimeError("assess broke")

    monkeypatch.setattr(runner_mod.DayDrafter, "run_snapshot_assessment", crash)
    agent_uc.QueueAgentRun(factory, alice).execute("assess")
    broken = _worker(config, session_factory, blobs, model, tmp_path).run_once()[0]
    assert broken.run.status == "failed" and "assess broke" in (broken.summary_md or "")


def test_t_agt_114_a_failing_checkup_leaves_it_out_of_the_summary(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-AGT-114: the run summary goes out without the check-up when the report fails."""
    capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(text="tea", target_date=DAY)
    )
    agent_uc.QueueAgentRun(factory, alice).execute("historical")

    def broken(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("report engine down")

    monkeypatch.setattr(runner_mod.ReportEngine, "render", broken)
    model = ScriptedModelClient(turns=[ScriptedTurn(text="Nothing.")])
    outcome = _worker(config, session_factory, blobs, model, tmp_path).run_once()[0]
    assert outcome.summary_md is not None and "Check-up (14 d)" not in outcome.summary_md


def test_t_agt_115_worker_failures_are_contained(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-AGT-115: a run another worker took is skipped; a processor that raises marks the run
    failed; when even that fails, the tick still returns."""
    run = agent_uc.QueueAgentRun(factory, alice).execute("historical")
    worker = _worker(config, session_factory, blobs, ScriptedModelClient(turns=[]), tmp_path)

    from victus.application.errors import RunNotActive

    def taken(self: Any, run_id: str) -> Any:
        raise RunNotActive("taken")

    monkeypatch.setattr(worker_mod.RunProcessor, "process", taken)
    assert worker.process_run(alice.tenant_id, run.id) is None

    def boom(self: Any, run_id: str) -> Any:
        raise RuntimeError("processor exploded")

    monkeypatch.setattr(worker_mod.RunProcessor, "process", boom)
    assert worker.process_run(alice.tenant_id, run.id) is None
    stored = agent_uc.GetAgentRun(factory, alice).execute(run.id)
    assert stored.status == "failed" and stored.error == "processor exploded"

    def no_finish(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("database gone")

    monkeypatch.setattr(worker_mod.agent_uc.FinishAgentRun, "execute", no_finish)
    assert worker.process_run(alice.tenant_id, run.id) is None


def test_t_agt_116_worker_lifecycle(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-AGT-116: a stop request ends the tick before the next run and the loop before the
    next tick; the signal handlers ask for that stop; a failing tick does not end the loop;
    an API key builds the Anthropic client."""
    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    worker = _worker(config, session_factory, blobs, ScriptedModelClient(turns=[]), tmp_path)
    worker.stop()
    assert worker.run_once() == []
    assert agent_uc.ListAgentRuns(factory, alice).execute(status="queued")

    installed: dict[int, Any] = {}
    monkeypatch.setattr(worker_mod.signal, "signal", lambda sig, fn: installed.setdefault(sig, fn))
    fresh = _worker(config, session_factory, blobs, None, tmp_path)
    fresh.install_signal_handlers()
    assert set(installed) == {signal.SIGINT, signal.SIGTERM}
    installed[signal.SIGTERM](signal.SIGTERM, None)
    assert fresh._stop.is_set()

    ticks: list[int] = []

    def tick(self: Worker) -> list[Any]:
        ticks.append(1)
        if len(ticks) == 1:
            raise RuntimeError("first tick fails")
        self.stop()
        return []

    monkeypatch.setattr(Worker, "run_once", tick)
    looping = _worker(config, session_factory, blobs, None, tmp_path)
    monkeypatch.setattr(looping._stop, "wait", lambda _s: False)
    looping.run_forever()
    assert len(ticks) == 2

    config.providers.anthropic_api_key = SecretStr("sk-ant-test")
    client = worker_mod.default_model_factory(config)
    assert client is not None and client.model == config.agent.model


def test_t_agt_117_purge_and_cron_skip(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-117: the tick purges a capture discarded long ago, and the schedule does not
    queue a second historical run while one is waiting."""
    cap = capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(text="old")
    )
    with session_factory() as s:
        row = s.get(orm.Capture, cap.id)
        assert row is not None
        row.status, row.processed_at = "discarded", datetime(2026, 1, 1, tzinfo=UTC)
        s.commit()
    worker = _worker(config, session_factory, blobs, None, tmp_path)
    assert worker.purge_settled_captures(datetime(2026, 3, 1, tzinfo=UTC)) == 1

    config.agent.enabled = True
    config.agent.cron = "0 * * * *"
    cron = _worker(config, session_factory, blobs, None, tmp_path)
    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    queued = cron.queue_scheduled_runs(datetime(2026, 3, 10, 14, 0, tzinfo=UTC))
    assert queued == 1, "bob gets one; alice already has one waiting"
    assert len(agent_uc.ListAgentRuns(factory, alice).execute(status="queued")) == 1


def test_t_agt_118_legacy_image_refs_and_unreadable_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-AGT-118: an image capture from before multi-file uploads still yields its one image;
    rules that cannot be read leave the prompt without them instead of failing the run."""
    from types import SimpleNamespace

    from victus.application.errors import NotFound

    legacy = SimpleNamespace(attachments=[], attachment_id="att_1", kind="image")
    refs = runner_mod._image_refs(legacy)  # type: ignore[arg-type]
    assert [r.id for r in refs] == ["att_1"]

    def unreadable(*_a: Any, **_k: Any) -> Any:
        raise NotFound("no settings")

    monkeypatch.setattr(runner_mod.rules_uc.ListRules, "execute", unreadable)
    tc = SimpleNamespace(uow_factory=None, ctx=None)
    assert runner_mod.tenant_rules(tc, "days") == ""  # type: ignore[arg-type]


def test_t_agt_119_a_draft_in_the_last_turn_or_over_budget_counts(
    factory: UowFactory,
    alice: TenantContext,
    skyr: int,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-119: a day drafted in the turn that spends the budget stays ``drafted``, and so
    does one drafted before the turn limit runs out; without blob storage the session gets
    no images and is not told about any."""
    from tests.integration.agent.test_runner import _draft_input

    blobs = InMemoryBlobStorage()
    cap = capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(text="breakfast: skyr", target_date=DAY)
    )
    holder: dict[str, str] = {}
    holder["run"] = agent_uc.QueueAgentRun(factory, alice).execute("historical").id
    config.agent.budget.max_output_tokens = 100
    model = ScriptedModelClient(
        turns=[
            ScriptedTurn(
                tool_calls=[("draft_create", lambda _m: _draft_input(holder["run"], cap.id, skyr))]
            )
        ]
    )
    over = _worker(config, session_factory, None, model, tmp_path).run_once()[0]  # type: ignore[arg-type]
    assert [d.outcome for d in over.days] == ["drafted"]
    assert not any(b.get("type") == "image" for b in model.calls[0]["messages"][0]["content"])

    config.agent.budget.max_output_tokens = 40_000
    config.agent.max_turns_per_day = 2
    from victus.application.use_cases import drafts as drafts_uc

    drafts_uc.DiscardDraft(factory, alice).execute(DAY)
    cap = capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(text="lunch: skyr again", target_date=DAY)
    )
    holder["run"] = agent_uc.QueueAgentRun(factory, alice).execute("historical").id
    busy = ScriptedModelClient(
        turns=[
            ScriptedTurn(
                tool_calls=[("draft_create", lambda _m: _draft_input(holder["run"], cap.id, skyr))]
            ),
            ScriptedTurn(tool_calls=[("product_search", {"q": "skyr"})]),
        ]
    )
    last = _worker(config, session_factory, blobs, busy, tmp_path).run_once()[0]
    assert [d.outcome for d in last.days] == ["drafted"]


def test_t_agt_120_a_spoken_product_capture_is_transcribed_first(
    factory: UowFactory,
    alice: TenantContext,
    skyr: int,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-120: a voice note about a product is transcribed before its session, and the
    session reads the transcript."""
    capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(
            data=b"OggS-voice", filename="v.oga", mime="audio/ogg", product_id=skyr
        )
    )
    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    model = ScriptedModelClient(turns=[ScriptedTurn(text="Heard it.")])
    speech = FakeTranscription("the label now says 64 kcal")
    _worker(config, session_factory, blobs, model, tmp_path, transcription=speech).run_once()
    assert speech.calls
    assert "64 kcal" in _texts(model.calls[0]["messages"][0]["content"])


def test_t_agt_121_a_run_taken_elsewhere_is_left_out_of_the_tick(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-AGT-121: a queued run that another worker takes first yields no outcome."""
    from victus.application.errors import RunNotActive

    agent_uc.QueueAgentRun(factory, alice).execute("historical")

    def taken(self: Any, run_id: str) -> Any:
        raise RunNotActive("taken")

    monkeypatch.setattr(worker_mod.RunProcessor, "process", taken)
    worker = _worker(config, session_factory, blobs, ScriptedModelClient(turns=[]), tmp_path)
    assert worker.run_once() == []
