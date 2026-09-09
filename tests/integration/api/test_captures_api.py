"""Captures and attachments over HTTP (multipart upload, transcription, isolation)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from victus.infrastructure.transcription.fake import FakeTranscription

pytestmark = pytest.mark.api

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478"
    "9c6360000002000154a24f5d0000000049454e44ae426082"
)
DAY = "2026-03-10"


def _upload_text(client: TestClient, headers: dict[str, str], text: str, day: str | None = None):  # type: ignore[no-untyped-def]
    data = {"text": text}
    if day:
        data["target_date"] = day
    return client.post("/api/v1/captures", data=data, headers=headers)


def test_text_capture_upload_and_duplicate(client: TestClient, alice_token: dict[str, str]) -> None:
    r = _upload_text(client, alice_token, "lunch: 400 g quark", DAY)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "text" and body["status"] == "new" and body["created"] is True
    assert body["target_date"] == DAY and body["text"] == "lunch: 400 g quark"
    dup = _upload_text(client, alice_token, "lunch: 400 g quark")
    assert dup.status_code == 200 and dup.json()["id"] == body["id"]
    assert dup.json()["created"] is False
    empty = client.post("/api/v1/captures", data={}, headers=alice_token)
    assert empty.status_code == 422


def test_the_day_thread_lists_every_file_of_a_capture(
    client: TestClient, alice_token: dict[str, str]
) -> None:
    """A capture of two photos and a voice note shows both photos in the day (R65).

    The thread used to carry `attachment_id` only — whichever file arrived first — so a
    capture that began with a photo showed no audio, and one that began with the voice
    note showed no photos.
    """
    r = client.post(
        "/api/v1/captures",
        data={"target_date": DAY},
        files=[
            ("file", ("label.png", PNG, "image/png")),
            ("file", ("second.png", PNG + b"x", "image/png")),
            ("file", ("voice.webm", b"OggS-fake-audio", "audio/webm")),
        ],
        headers=alice_token,
    )
    assert r.status_code == 201, r.text
    cap = r.json()
    assert cap["kind"] == "audio", "audio in the capture makes it an audio capture"
    assert len(cap["attachments"]) == 3

    thread = client.get(f"/api/v1/days/{DAY}/messages", headers=alice_token).json()
    entry = next(m for m in thread if m["capture_id"] == cap["id"])
    mimes = [a["mime"] for a in entry["attachments"]]
    assert mimes.count("image/png") == 2 and "audio/webm" in mimes


def test_image_upload_and_attachment_download(
    client: TestClient, alice_token: dict[str, str], bob_token: dict[str, str]
) -> None:
    r = client.post(
        "/api/v1/captures",
        files={"file": ("label.png", PNG, "image/png")},
        headers=alice_token,
    )
    assert r.status_code == 201, r.text
    cap = r.json()
    assert cap["kind"] == "image" and cap["attachment_mime"] == "image/png"
    att = client.get(f"/api/v1/attachments/{cap['attachment_id']}", headers=alice_token)
    assert att.status_code == 200
    assert att.content == PNG and att.headers["content-type"].startswith("image/png")
    assert "inline" in att.headers["content-disposition"]
    assert att.headers["cache-control"] == "private, max-age=3600"
    # other tenant: 404 on every route
    assert (
        client.get(f"/api/v1/attachments/{cap['attachment_id']}", headers=bob_token).status_code
        == 404
    )
    assert client.get(f"/api/v1/captures/{cap['id']}", headers=bob_token).status_code == 404
    assert (
        client.patch(
            f"/api/v1/captures/{cap['id']}", json={"status": "discarded"}, headers=bob_token
        ).status_code
        == 404
    )
    assert (
        client.post(f"/api/v1/captures/{cap['id']}/transcribe", headers=bob_token).status_code
        == 404
    )
    assert client.get("/api/v1/captures", headers=bob_token).json() == []
    unsupported = client.post(
        "/api/v1/captures",
        files={"file": ("x.pdf", b"%PDF-1.7", "application/pdf")},
        headers=alice_token,
    )
    assert unsupported.status_code == 422


def test_audio_upload_is_transcribed_when_configured(
    api_app: FastAPI, client: TestClient, alice_token: dict[str, str]
) -> None:
    fake = FakeTranscription("a whole tub of skyr")
    api_app.state.transcription = fake
    try:
        r = client.post(
            "/api/v1/captures",
            files={"file": ("note.oga", b"OggS-fake", "application/octet-stream")},
            data={"target_date": DAY},
            headers=alice_token,
        )
        assert r.status_code == 201, r.text
        cap = r.json()
        assert cap["kind"] == "audio" and cap["transcript"] == "a whole tub of skyr"
        assert fake.calls[0]["mime"] == "audio/ogg"
        # force re-transcription
        fake.text = "half a tub of skyr"
        again = client.post(
            f"/api/v1/captures/{cap['id']}/transcribe?force=true", headers=alice_token
        )
        assert again.status_code == 200 and again.json()["transcript"] == "half a tub of skyr"
        # provider failure on upload keeps the capture (status failed) and still answers 201
        api_app.state.transcription = FakeTranscription(fail=True)
        failed = client.post(
            "/api/v1/captures",
            files={"file": ("other.wav", b"RIFF-other", "audio/wav")},
            headers=alice_token,
        )
        assert failed.status_code == 201 and failed.json()["status"] == "failed"
        retry = client.post(
            f"/api/v1/captures/{failed.json()['id']}/transcribe", headers=alice_token
        )
        assert retry.status_code == 502
    finally:
        api_app.state.transcription = None
    # without a provider, an explicit transcribe request is a 502 problem
    r2 = client.post(f"/api/v1/captures/{cap['id']}/transcribe?force=true", headers=alice_token)
    assert r2.status_code == 502
    assert r2.headers["content-type"].startswith("application/problem+json")


def test_list_filter_patch(client: TestClient, alice_token: dict[str, str]) -> None:
    a = _upload_text(client, alice_token, "one", DAY).json()
    b = _upload_text(client, alice_token, "two").json()
    listed = client.get("/api/v1/captures", headers=alice_token).json()
    assert {c["id"] for c in listed} == {a["id"], b["id"]}
    by_day = client.get(f"/api/v1/captures?date={DAY}", headers=alice_token).json()
    assert [c["id"] for c in by_day] == [a["id"]]
    patched = client.patch(
        f"/api/v1/captures/{b['id']}", json={"target_date": "2026-03-11"}, headers=alice_token
    )
    assert patched.status_code == 200 and patched.json()["target_date"] == "2026-03-11"
    discarded = client.patch(
        f"/api/v1/captures/{a['id']}", json={"status": "discarded"}, headers=alice_token
    )
    assert discarded.status_code == 200 and discarded.json()["status"] == "discarded"
    only_new = client.get("/api/v1/captures?status=new", headers=alice_token).json()
    assert [c["id"] for c in only_new] == [b["id"]]
    assert client.get("/api/v1/captures?status=bogus", headers=alice_token).status_code == 422
    assert (
        client.patch(
            f"/api/v1/captures/{a['id']}", json={"status": "bogus"}, headers=alice_token
        ).status_code
        == 422
    )
    assert client.get("/api/v1/captures/missing", headers=alice_token).status_code == 404


def test_capture_routes_require_scopes(
    client: TestClient,
    api_factory,
    alice_account,  # type: ignore[no-untyped-def]
) -> None:
    from tests.integration.api.conftest import bearer

    read_only = bearer(api_factory, alice_account, ["read"])
    assert client.get("/api/v1/captures", headers=read_only).status_code == 403
    assert _upload_text(client, read_only, "x").status_code == 403
    assert client.get("/api/v1/captures", headers={}).status_code == 401
