"""
Speech-to-text — WhatsApp voice notes become text, then flow through the SAME pipeline as a
typed message (wake word → role gate → grounded agent → guard). Voice adds an input channel,
never a second brain.

Pluggable, OpenAI-compatible /audio/* endpoint (Groq Whisper by default). Provider/model/key
come from the admin panel (DB '_stt') first, then env — never env-only, same contract as the
LLM and embeddings layers. No key configured → transcribe() returns {} and the caller degrades
(the bot tells the sender it can't hear voice notes yet); it never guesses at the audio.

WhatsApp voice notes are OGG/Opus, which Whisper accepts natively — no ffmpeg transcode.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# provider → (key_env, default_base_url, default_model)
STT_PROVIDERS = {
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "whisper-large-v3"),
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1", "whisper-1"),
    "custom": ("", "", ""),
}
# NOTE: only whisper-large-v3 / whisper-1 support the TRANSLATION endpoint (audio → English).
# The turbo + distil models are transcription-only; translate=True on those degrades to a
# native-language transcript rather than failing.
STT_CATALOG = {
    "groq": ["whisper-large-v3", "whisper-large-v3-turbo", "distil-whisper-large-v3-en"],
    "openai": ["whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"],
    "custom": [],
}
_TRANSLATE_CAPABLE = ("whisper-large-v3", "whisper-1")

_CONFIG_DB = None


def set_config_db(db) -> None:
    global _CONFIG_DB
    _CONFIG_DB = db


def _stt_config():
    """(provider, base_url, api_key, model). Precedence: the admin panel's saved config
    (DB '_stt') → ARVISX_STT_* env → the Groq key already in the environment."""
    if _CONFIG_DB is not None:
        try:
            prov = (_CONFIG_DB.get_setting("_stt", "provider", "") or "").strip().lower()
            key = (_CONFIG_DB.get_setting("_stt", "api_key", "") or "").strip()
            if prov and key:
                _e, dbase, dmodel = STT_PROVIDERS.get(prov, ("", "", ""))
                base = (_CONFIG_DB.get_setting("_stt", "base_url", "") or "").strip() or dbase
                model = (_CONFIG_DB.get_setting("_stt", "model", "") or "").strip() or dmodel
                if base and model:
                    return prov, base, key, model
        except Exception:
            pass
    prov = (os.environ.get("ARVISX_STT_PROVIDER", "groq") or "groq").strip().lower()
    key_env, dbase, dmodel = STT_PROVIDERS.get(prov, STT_PROVIDERS["groq"])
    base = os.environ.get("ARVISX_STT_BASE_URL") or dbase
    key = os.environ.get("ARVISX_STT_KEY") or (os.environ.get(key_env, "") if key_env else "")
    model = os.environ.get("ARVISX_STT_MODEL") or dmodel
    return prov, base, key, model


def stt_available() -> bool:
    _p, _b, key, _m = _stt_config()
    return bool(key)


def transcribe(audio: bytes, filename: str = "voice.ogg", translate: bool = True,
               seconds: float = 0.0, building: str = "") -> Dict[str, Any]:
    """Voice note bytes → text. `translate=True` returns ENGLISH regardless of the language
    spoken (Hindi/Kannada/English are all mixed on site, and the agent prompts + grounding guard
    are English) — on a transcription-only model it degrades to a native-language transcript
    instead of failing. Returns {} when unconfigured or the call fails: the caller must handle
    silence, never invent what was said."""
    prov, base, key, model = _stt_config()
    if not key or not audio:
        return {}
    want_translate = translate and any(model.startswith(m) for m in _TRANSLATE_CAPABLE)
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=base, timeout=60.0, max_retries=1)
        f = (filename or "voice.ogg", audio)
        if want_translate:
            resp = client.audio.translations.create(model=model, file=f)
        else:
            resp = client.audio.transcriptions.create(model=model, file=f)
    except Exception as e:
        logger.warning(f"[stt:{prov}] transcription failed: {e}")
        return {}
    text = (getattr(resp, "text", "") or "").strip()
    if not text:
        return {}
    try:
        from arvisx import metrics
        metrics.record_stt(model, seconds or 0.0, building=building)
    except Exception:
        pass
    return {"text": text, "model": model, "provider": prov,
            "translated": bool(want_translate), "seconds": seconds}
