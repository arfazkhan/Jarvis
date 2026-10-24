"""
LLM-Vision OCR Backend
======================

Escalation backend for pages Docling cannot crack — pure diagrams, poor scans,
rotated/handwritten content. Renders happen upstream (fitz → PNG); this backend
sends the page image to a vision-capable, OpenAI-compatible model and asks for a
faithful text/markdown transcription.

Provider wiring mirrors bms_llm_agent.update_config: a vision-capable model is
required (gpt-4o-mini, or an OpenRouter vision model). K2Think/Groq text-only
defaults will NOT work here, so this backend resolves its own client from
env vars, independent of the runtime agent's text model.
"""

from __future__ import annotations

import base64
import logging
import os
import re

from agent_commercial.skills.backends.ocr_base import OCRBackend, PageOCRResult

logger = logging.getLogger("arvis.skills.ocr.vision")

_TRANSCRIBE_PROMPT = (
    "You are an OCR engine for technical equipment manuals. Transcribe ALL text "
    "in this page image verbatim into clean markdown. Preserve tables as markdown "
    "tables, preserve fault-code lists and parameter tables exactly, keep headings. "
    "For diagrams, transcribe every label and callout, and add a one-line "
    "[diagram: ...] description. Do NOT summarize, invent, or omit. If a region is "
    "illegible, write [illegible]. Output only the transcription, no commentary, "
    "no reasoning."
)

# (provider, env_var, base_url, default_vision_model)
# Groq is preferred here — the project's live key. qwen3.6-27b is vision-capable.
_VISION_PROVIDERS = [
    ("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1", "qwen/qwen3.6-27b"),
    ("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1",
     "openai/gpt-4o-mini"),
    ("gemini", "GEMINI_API_KEY",
     "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-1.5-flash"),
    ("openai", "OPENAI_API_KEY", None, "gpt-4o-mini"),
]


class VisionBackend(OCRBackend):
    name = "llm-vision"

    def __init__(self, model: str | None = None) -> None:
        self._client = None
        self._model = model
        self._pool = None  # GroqKeyPool when Groq keys are present
        self._resolve_client()

    def _resolve_client(self) -> None:
        try:
            from openai import OpenAI
        except Exception:
            logger.warning("openai package not available; vision backend disabled")
            return
        # Prefer the shared Groq key pool (rotates on rate limits) when Groq keys
        # are configured. Same pool the analyzer uses — cooldowns are shared.
        try:
            from agent_commercial.skills.groq_pool import GroqKeyPool
            pool = GroqKeyPool()
            if pool.available:
                self._pool = pool
                self._model = self._model or "qwen/qwen3.6-27b"
                logger.info("Vision OCR using Groq key pool (%d keys) model=%s",
                            pool.size, self._model)
                return
        except Exception as e:
            logger.debug("Groq pool init skipped for vision: %s", e)
        for provider, env_var, base_url, default_model in _VISION_PROVIDERS:
            key = os.getenv(env_var, "").strip()
            if not key:
                continue
            try:
                kwargs = {"api_key": key}
                if base_url:
                    kwargs["base_url"] = base_url
                self._client = OpenAI(**kwargs)
                self._model = self._model or default_model
                logger.info("Vision OCR using provider=%s model=%s", provider, self._model)
                return
            except Exception as e:
                logger.warning("Vision provider %s init failed: %s", provider, e)
        logger.warning(
            "No vision-capable API key found (%s). Vision escalation disabled.",
            ", ".join(env for _, env, _, _ in _VISION_PROVIDERS),
        )

    @property
    def available(self) -> bool:
        return self._client is not None or self._pool is not None

    def extract_page(self, png_bytes: bytes, page_no: int) -> PageOCRResult:
        if not self.available:
            return PageOCRResult(page_no=page_no, text="", backend=self.name, confidence=0.0)
        try:
            text = self.describe(png_bytes, _TRANSCRIBE_PROMPT, max_tokens=8192)
        except Exception as e:
            logger.warning("Vision OCR failed on page %d: %s", page_no, e)
            return PageOCRResult(page_no=page_no, text="", backend=self.name, confidence=0.0)

        # Confidence: vision transcription is high-fidelity when it returns
        # substantive text; illegible markers lower it.
        conf = 0.9 if text else 0.0
        if "[illegible]" in text:
            conf -= 0.2 * (text.count("[illegible]") > 3)
        return PageOCRResult(page_no=page_no, text=text, backend=self.name,
                             confidence=round(max(conf, 0.0), 3))

    def describe(self, image_bytes: bytes, prompt: str, max_tokens: int = 1024) -> str:
        """Ask the vision model about one image. Raises when no provider is configured
        or the call fails — callers decide what to say then."""
        if not self.available:
            raise RuntimeError("no vision-capable model configured")
        # Downscale + JPEG-compress: full-res images exceed the model's request-size
        # limit (Groq qwen returns 413). Cap the long side and send JPEG.
        img_bytes, mime = self._prepare_image(image_bytes)
        data_url = f"data:{mime};base64,{base64.b64encode(img_bytes).decode('ascii')}"
        call_kwargs = dict(
            model=self._model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            temperature=0.0,
            max_tokens=max_tokens,
            extra_body={"reasoning_effort": "none"},
        )
        if self._pool is not None:
            resp = self._pool.chat_completion(**call_kwargs)
        else:
            resp = self._client.chat.completions.create(**call_kwargs)
        return self._strip_reasoning((resp.choices[0].message.content or "").strip())

    # Long-side cap in pixels for the vision request. Kept small deliberately:
    # Groq free-tier qwen has an 8000 tokens/min limit and image tokens scale
    # with resolution — a full-res page render alone (~10.6k tok) exceeds it.
    # ~1000px keeps a single page image well under the TPM budget so escalation
    # of a flagged page succeeds. Vision is best-effort escalation only; the
    # pipeline never depends on it (RapidOCR does the bulk locally).
    _MAX_LONG_SIDE = 1000

    def _prepare_image(self, png_bytes: bytes) -> tuple[bytes, str]:
        """Downscale to _MAX_LONG_SIDE and re-encode as JPEG. Falls back to the
        original PNG if PIL is unavailable."""
        try:
            import io
            from PIL import Image
            img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            w, h = img.size
            long_side = max(w, h)
            if long_side > self._MAX_LONG_SIDE:
                scale = self._MAX_LONG_SIDE / long_side
                img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue(), "image/jpeg"
        except Exception as e:
            logger.debug("Image prep fell back to raw PNG: %s", e)
            return png_bytes, "image/png"

    @staticmethod
    def _strip_reasoning(text: str) -> str:
        """Reasoning models (e.g. qwen3.6) wrap output in <think>...</think>.
        Drop the reasoning and keep the final transcription. If the closing tag
        is missing (truncated mid-think), drop everything up to the last think
        marker so we never leak chain-of-thought into the compiled skill."""
        # Remove complete think blocks.
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # Handle an unclosed trailing/leading think block.
        if "<think>" in cleaned.lower():
            idx = cleaned.lower().rfind("</think>")
            if idx != -1:
                cleaned = cleaned[idx + len("</think>"):]
            else:
                # all-think, no final answer — nothing usable
                cleaned = re.sub(r"<think>.*", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        return cleaned.strip()
