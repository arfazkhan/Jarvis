"""Voice notes: audio → text → the SAME pipeline as a typed message.

The contract under test:
- STT config resolves DB-first (admin panel), then env — never env-only.
- No key configured → transcribe() returns {} and the caller degrades. It NEVER guesses at
  what was said (a fabricated transcript would poison every downstream grounded answer).
- /voice/transcribe reports available:false rather than inventing text.
- /whatsapp/observe logs what was said WITHOUT replying (passive capture of group voice).
- Whisper cost is metered per audio-second.
"""
from __future__ import annotations

import pytest

import arvisx.stt as stt
from arvisx.metrics import stt_cost
from arvisx.persistence import ArvisxDb

_NO_KEYS = ("ARVISX_STT_KEY", "GROQ_API_KEY", "OPENAI_API_KEY")


@pytest.fixture(autouse=True)
def _reset_stt_config():
    """create_app() wires the module-level config DB — don't leak it between tests."""
    yield
    stt.set_config_db(None)


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from arvisx.api import create_app
    path = str(tmp_path / "voice.db")
    monkeypatch.setenv("ARVISX_DB", path)
    return TestClient(create_app()), ArvisxDb(path)


# ── config resolution ───────────────────────────────────────────────────────
def test_stt_config_prefers_admin_panel_over_env(tmp_path, monkeypatch):
    db = ArvisxDb(str(tmp_path / "cfg.db"))
    monkeypatch.setenv("ARVISX_STT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    db.set_setting("_stt", "provider", "groq")
    db.set_setting("_stt", "api_key", "db-key")
    db.set_setting("_stt", "model", "whisper-large-v3")
    stt.set_config_db(db)
    prov, base, key, model = stt._stt_config()
    assert prov == "groq" and key == "db-key" and model == "whisper-large-v3"
    assert "groq.com" in base
    assert stt.stt_available()


def test_stt_config_falls_back_to_env(monkeypatch):
    stt.set_config_db(None)
    monkeypatch.setenv("ARVISX_STT_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "env-groq")
    prov, _base, key, model = stt._stt_config()
    assert prov == "groq" and key == "env-groq" and model == "whisper-large-v3"


def test_no_key_means_silence_not_a_guessed_transcript(monkeypatch):
    stt.set_config_db(None)
    for v in _NO_KEYS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("ARVISX_STT_PROVIDER", "groq")
    assert not stt.stt_available()
    assert stt.transcribe(b"\x00\x01fake-ogg-bytes") == {}


def test_transcribe_empty_audio_is_empty(monkeypatch):
    stt.set_config_db(None)
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert stt.transcribe(b"") == {}


# ── only translate-capable models translate ─────────────────────────────────
def test_only_translate_capable_models_translate():
    assert "whisper-large-v3" in stt._TRANSLATE_CAPABLE
    # turbo is transcription-only — it must not be silently treated as a translator
    assert "whisper-large-v3-turbo" not in stt._TRANSLATE_CAPABLE
    assert "whisper-large-v3-turbo" in stt.STT_CATALOG["groq"]


# ── cost metering ───────────────────────────────────────────────────────────
def test_stt_cost_is_per_audio_hour(monkeypatch):
    monkeypatch.setenv("ARVISX_STT_PRICE", "9.5")      # ₹ per audio-hour
    assert stt_cost(3600) == 9.5
    assert stt_cost(0) == 0.0
    assert 0 < stt_cost(20) < 0.06                      # a 20s note is a rounding error


# ── passive capture: observed, not answered ─────────────────────────────────
def test_observe_logs_without_replying(tmp_path, monkeypatch):
    client, db = _client(tmp_path, monkeypatch)
    r = client.post("/api/v1/whatsapp/observe",
                    json={"text": "the lift is making a grinding noise again", "name": "Resident A"})
    assert r.status_code == 200 and r.json()["logged"] is True
    rows = db.chat_since("one-anthem", "2000-01-01")
    hit = [t for t in rows if "grinding noise" in (t.get("text") or "")]
    assert hit, "observed voice note should land in the chat log (recall/decisions can see it)"
    assert all((t.get("reply") or "") == "" for t in hit), "observed, not answered — no reply"


def test_observe_ignores_empty_text(tmp_path, monkeypatch):
    client, _db = _client(tmp_path, monkeypatch)
    assert client.post("/api/v1/whatsapp/observe", json={"text": "  "}).json()["logged"] is False


# ── the endpoint degrades honestly when STT isn't configured ────────────────
def test_transcribe_endpoint_reports_unavailable(tmp_path, monkeypatch):
    for v in _NO_KEYS:
        monkeypatch.delenv(v, raising=False)
    client, _db = _client(tmp_path, monkeypatch)
    r = client.post("/api/v1/voice/transcribe", content=b"\x00\x01not-real-audio")
    assert r.status_code == 200
    assert r.json() == {"text": "", "available": False}      # no invented transcript


def test_transcribe_endpoint_rejects_empty_body(tmp_path, monkeypatch):
    client, _db = _client(tmp_path, monkeypatch)
    assert client.post("/api/v1/voice/transcribe", content=b"").status_code == 400
