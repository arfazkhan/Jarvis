"""
Semantic chat recall — embeddings over the full conversation history.

Pluggable, OpenAI-compatible embeddings API (ARVISX_EMBED_* env, else reuse the LLM provider's
key/base). Vectors are stored as float32 blobs in chat_embedding; scoring is a pure-Python cosine
(no numpy dep — a chat history of a few thousand short turns scores in well under a second). If no
embeddings provider is configured, callers fall back to keyword search — recall degrades, never
breaks. Nothing here fabricates: search only ranks real stored turns.
"""
from __future__ import annotations

import array
import math
import os
from typing import List, Optional, Tuple


def _embed_config():
    """(base_url, api_key, model) for the embeddings endpoint. Explicit ARVISX_EMBED_* wins;
    otherwise reuse the configured LLM provider's key/base (same OpenAI-compatible host)."""
    from arvisx.llm_client import _PROVIDERS
    prov = os.environ.get("ARVISX_LLM_PROVIDER", "k2think").strip().lower()
    key_env, base, _model = _PROVIDERS.get(prov, _PROVIDERS["k2think"])
    base_url = os.environ.get("ARVISX_EMBED_BASE_URL") or base
    key = os.environ.get("ARVISX_EMBED_KEY") or os.environ.get(key_env, "")
    model = os.environ.get("ARVISX_EMBED_MODEL", "text-embedding-3-small")
    return base_url, key, model


def embeddings_available() -> bool:
    _b, key, _m = _embed_config()
    return bool(key)


def embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    """Embed a batch. Returns vectors, or None if not configured / the call fails (→ keyword)."""
    base_url, key, model = _embed_config()
    if not key or not texts:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=base_url)
        resp = client.embeddings.create(model=model, input=[t[:2000] for t in texts])
        return [list(d.embedding) for d in resp.data]
    except Exception:
        return None


def embed_one(text: str) -> Optional[List[float]]:
    v = embed_texts([text])
    return v[0] if v else None


# ── vector <-> blob (float32) + cosine (pure Python) ──────────────────────
def to_blob(vec: List[float]) -> bytes:
    return array.array("f", vec).tobytes()


def from_blob(b: bytes) -> array.array:
    a = array.array("f")
    a.frombytes(b)
    return a


def _cosine(a, b) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def top_k(query_vec: List[float], items: List[Tuple[int, bytes]], k: int = 6,
          min_score: float = 0.2) -> List[Tuple[int, float]]:
    """items = [(chat_id, vec_blob)]. Returns [(chat_id, score)] top-k above min_score."""
    scored = []
    for cid, blob in items:
        try:
            v = from_blob(blob)
        except Exception:
            continue
        s = _cosine(query_vec, v)
        if s >= min_score:
            scored.append((cid, s))
    scored.sort(key=lambda x: -x[1])
    return scored[:k]
