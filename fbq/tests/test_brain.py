"""The 'learns everything' core, hermetic (no LLM, no STT key → deterministic floors):
voice → same text brain · photo → ask-don't-analyse → human's answer becomes memory ·
"remember X" → brain · recall months later · end-of-day becomes a memory."""
import pytest
from fastapi.testclient import TestClient

from fbq import brain

GJ = "12036302@g.us"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FBQ_DB", str(tmp_path / "fbq.db"))
    monkeypatch.setenv("FBQ_MEDIA_DIR", str(tmp_path / "media"))
    for k in ("FBQ_LLM", "ARVIS_X_LLM", "GROQ_API_KEY", "ARVISX_STT_KEY", "ARVISX_EMBED_KEY"):
        monkeypatch.delenv(k, raising=False)
    from fbq.api import create_app
    return TestClient(create_app())


def _proj(client) -> int:
    return client.post("/api/v1/projects", json={
        "name": "3BHK Indiranagar", "template_id": "P3-MANUF-EXEC",
        "start_date": "2026-07-01", "group_jid": GJ}).json()["id"]


def _say(client, text, phone="919900011122", name="Ravi"):
    return client.post("/api/v1/ingest", json={
        "group_jid": GJ, "phone": phone, "name": name, "text": text, "kind": "text"}).json()["reply"]


def _send_media(client, kind, data=b"\x89PNG-fake", filename="site.jpg",
                phone="919900011122", name="Ravi", seconds=0):
    return client.post("/api/v1/media", content=data,
                       params={"group_jid": GJ, "phone": phone, "name": name, "kind": kind,
                               "filename": filename, "seconds": seconds},
                       headers={"Content-Type": "application/octet-stream"}).json()["reply"]


# ── intent parsers ────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,want", [
    ("remember the client wants matte finish", "the client wants matte finish"),
    ("Remember: kitchen handles are brass", "kitchen handles are brass"),
    ("yaad rakhna the plumber comes on monday", "the plumber comes on monday"),
    ("note that client approved the veneer", "client approved the veneer"),
    ("false ceiling is done", ""),                 # not a remember
])
def test_remember_parsing(text, want):
    assert brain.remember_request(text) == want


@pytest.mark.parametrize("text,want", [
    ("what did we say about the countertop?", "the countertop"),
    ("when did we decide on the veneer finish?", "the veneer finish"),
    ("did we ever discuss about the false ceiling", "the false ceiling"),
    ("false ceiling is done", ""),                 # not a recall
])
def test_recall_parsing(text, want):
    assert brain.recall_request(text) == want


# ── photo: ask, don't analyse ─────────────────────────────────────────────
def test_photo_asks_and_human_answer_becomes_memory(client):
    pid = _proj(client)
    r = _send_media(client, "photo")
    assert "what's this about" in r.lower()
    # the human's next message IS the context — no image analysis anywhere
    r2 = _say(client, "kitchen shutters installed on the left wall")
    assert "Got it" in r2 and "kitchen shutters" in r2
    mem = client.get(f"/api/v1/projects/{pid}/memories").json()["memories"]
    assert any("kitchen shutters" in m["text"] and m["source"] == "photo" for m in mem)
    med = client.get(f"/api/v1/projects/{pid}/media").json()["media"]
    assert med and med[0]["caption"].startswith("kitchen shutters")


def test_photo_caption_is_scoped_to_the_sender(client):
    _proj(client)
    _send_media(client, "photo", phone="919900011122", name="Ravi")
    # someone ELSE talking must not be swallowed as Ravi's caption
    r = _say(client, "good morning all", phone="918800022233", name="Suresh")
    assert "Got it" not in r


# ── voice: same brain, no second pipeline ─────────────────────────────────
def test_voice_without_stt_key_stays_silent(client):
    """No STT configured → say nothing rather than guess at the audio."""
    _proj(client)
    assert _send_media(client, "voice", data=b"OggS-fake", filename="voice.ogg", seconds=6) == ""


# ── remember + recall ─────────────────────────────────────────────────────
def test_remember_then_recall(client):
    pid = _proj(client)
    r = _say(client, "remember the client wants matte finish on all shutters")
    assert "remember that" in r.lower()
    # recall — keyword fallback (no embeddings key configured)
    ans = _say(client, "@firstbriq what did we say about the finish?")
    assert "matte" in ans.lower()
    mem = client.get(f"/api/v1/projects/{pid}/memories").json()["memories"]
    assert any(m["source"] == "remember" for m in mem)


def test_recall_endpoint_and_empty_case(client):
    pid = _proj(client)
    r = client.get(f"/api/v1/projects/{pid}/recall", params={"q": "granite"}).json()
    assert "nothing on record" in r["answer"].lower()
    _say(client, "remember granite slab arrives next tuesday")
    r2 = client.get(f"/api/v1/projects/{pid}/recall", params={"q": "granite"}).json()
    assert "granite" in r2["answer"].lower() and r2["hits"]


# ── the day becomes a memory ──────────────────────────────────────────────
def test_close_day_writes_memory_and_is_idempotent(client):
    pid = _proj(client)
    _say(client, "false ceiling work is completed")
    _say(client, "yes")                                  # confirm → task done
    r = client.post(f"/api/v1/projects/{pid}/close-day", json={}).json()["text"]
    assert "end of day" in r.lower()
    mems = client.get(f"/api/v1/projects/{pid}/memories").json()["memories"]
    daily = [m for m in mems if m["source"] == "daily"]
    assert len(daily) == 1
    client.post(f"/api/v1/projects/{pid}/close-day", json={})     # again — no duplicate
    daily2 = [m for m in client.get(f"/api/v1/projects/{pid}/memories").json()["memories"]
              if m["source"] == "daily"]
    assert len(daily2) == 1
    # and it was queued to the group as the evening brief
    out = client.get("/api/v1/outbox").json()["outbox"]
    assert any(o["kind"] == "evening_brief" for o in out)


def test_manual_memory_from_web(client):
    pid = _proj(client)
    client.post(f"/api/v1/projects/{pid}/memories", json={"text": "client prefers site visits on saturdays"})
    ans = client.get(f"/api/v1/projects/{pid}/recall", params={"q": "site visits"}).json()["answer"]
    assert "saturday" in ans.lower()
