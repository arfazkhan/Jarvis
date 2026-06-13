"""
ArvisX Agentic Phase-D — Vision (model-agnostic).

A technician photographs a DG panel / gauge / tank / electrical panel; the vision provider
proposes an extraction (meter readings, level %, condition findings). EVERYTHING here is
built except the actual multimodal model — that plugs in later via `register_vision_provider`
or ARVISX_VISION_PROVIDER, without touching the pipeline.

Safety (verify pattern): an extraction is a PROPOSAL, never auto-committed. The operator
sees the photo + the extracted value and confirms (one tap) before it's written to the
checklist entry. No model configured → the pipeline still runs and just reports
"vision not configured" — manual entry is unaffected.

Extraction schema (model-agnostic; the UI/confirm don't depend on exact fields):
  kind "gauge" / "panel"  → {"readings": {"voltage","current","frequency",...}, "confidence"}
  kind "level"            → {"level_pct", "confidence"}
  kind "condition"        → {"findings": [...], "recommended": "...", "confidence"}
"""
from __future__ import annotations

import base64
import os
from typing import Any, Dict, Optional

# ── extraction prompts (model-agnostic) ──────────────────────────────────
VISION_SYSTEM = (
    "You read industrial / building-equipment photos for a facility-operations checklist. "
    "Return ONLY a JSON object, no prose. Report ONLY what is clearly legible. If a value is "
    "blurred, cut off, glare-covered or ambiguous, set it to null and lower confidence — "
    "NEVER guess a number. 'confidence' is 0..1. The reading is shown to a human to confirm, "
    "so being honest about uncertainty matters more than filling every field."
)
KIND_PROMPTS: Dict[str, str] = {
    "gauge": ("Extract the panel/meter readings shown. JSON exactly: "
              '{"readings":{"voltage":<V|null>,"current":<A|null>,"frequency":<Hz|null>},'
              '"confidence":<0-1>,"unreadable":[<field names you could not read>]}. '
              "Read the digital/analog displays exactly as shown; do not infer or unit-convert."),
    "panel": ("Extract the panel/meter readings shown. JSON exactly: "
              '{"readings":{"voltage":<V|null>,"current":<A|null>,"frequency":<Hz|null>},'
              '"confidence":<0-1>,"unreadable":[...]}. Read displays exactly as shown.'),
    "level": ("Estimate the tank/reservoir level. JSON exactly: "
              '{"level_pct":<0-100|null>,"confidence":<0-1>,"basis":"sight glass|float|markings|none"}. '
              "If no scale/markings are visible, level_pct=null."),
    "condition": ("Inspect for VISIBLE defects only. JSON exactly: "
                  '{"findings":[<"dust"|"corrosion"|"loose cable gland"|"burn marks"|"moisture"|'
                  '"oil leak"|...>],"recommended":"<short action>","confidence":<0-1>}. '
                  "Report only conditions clearly visible in the image."),
    "auto": ("Identify what the photo shows and extract the most relevant facts. JSON: "
             '{"detected":"gauge|level|condition|other","readings":{...}|null,'
             '"level_pct":<0-100|null>,"findings":[...]|null,"confidence":<0-1>}. '
             "Only report clearly legible values; null + low confidence when unsure."),
}


class VisionProvider:
    name = "base"
    available = False

    def extract(self, image_bytes: bytes, kind: str = "auto", hint: str = "") -> Dict[str, Any]:
        raise NotImplementedError


class NullVisionProvider(VisionProvider):
    """Default — no model wired. The pipeline runs; extraction reports unavailable."""
    name = "null"
    available = False

    def extract(self, image_bytes: bytes, kind: str = "auto", hint: str = "") -> Dict[str, Any]:
        return {"available": False, "reason": "vision model not configured",
                "kind": kind, "extracted": {}}


def _data_url(image_bytes: bytes) -> str:
    """base64 data URL with a mime sniffed from magic bytes (jpeg/png/webp)."""
    mime = "image/jpeg"
    if image_bytes[:8].startswith(b"\x89PNG"):
        mime = "image/png"
    elif image_bytes[8:12] == b"WEBP":
        mime = "image/webp"
    return f"data:{mime};base64," + base64.b64encode(image_bytes).decode()


class OpenAICompatVisionProvider(VisionProvider):
    """Reference provider for any OpenAI-compatible multimodal endpoint (OpenAI gpt-4o,
    compatible gateways). Config: ARVISX_VISION_API_KEY (or OPENAI_API_KEY),
    ARVISX_VISION_BASE_URL, ARVISX_VISION_MODEL (default gpt-4o-mini). `client` injectable
    for tests. NOTE: Anthropic's native API uses a different image shape — add a sibling
    provider for it; this one covers the OpenAI-compatible family."""
    name = "openai-compat"
    available = True

    def __init__(self, client=None, model: str = ""):
        self.model = model or os.environ.get("ARVISX_VISION_MODEL", "gpt-4o-mini")
        if client is not None:
            self._client = client
            return
        key = os.environ.get("ARVISX_VISION_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("no vision API key (ARVISX_VISION_API_KEY / OPENAI_API_KEY)")
        from openai import OpenAI
        self._client = OpenAI(api_key=key, base_url=os.environ.get("ARVISX_VISION_BASE_URL") or None)

    def extract(self, image_bytes: bytes, kind: str = "auto", hint: str = "") -> Dict[str, Any]:
        from arvisx.llm_client import _extract_json
        instruction = KIND_PROMPTS.get(kind, KIND_PROMPTS["auto"])
        if hint:
            instruction += f"\nContext: {hint}"
        resp = self._client.chat.completions.create(
            model=self.model, temperature=0, max_tokens=500,
            messages=[{"role": "system", "content": VISION_SYSTEM},
                      {"role": "user", "content": [
                          {"type": "text", "text": instruction},
                          {"type": "image_url", "image_url": {"url": _data_url(image_bytes)}}]}])
        content = (resp.choices[0].message.content or "") if resp.choices else ""
        parsed = _extract_json(content) or {}
        return {"available": True, "kind": kind, "extracted": parsed,
                "confidence": parsed.get("confidence")}


_PROVIDER: Optional[VisionProvider] = None


def register_vision_provider(provider: VisionProvider) -> None:
    """Plug in a real multimodal model (Claude/GPT-4o/etc.) at runtime. The provider only
    needs extract(image_bytes, kind, hint) -> {"available":True,"extracted":{...},...}."""
    global _PROVIDER
    _PROVIDER = provider


def get_provider() -> VisionProvider:
    if _PROVIDER is not None:
        return _PROVIDER
    name = os.environ.get("ARVISX_VISION_PROVIDER", "").strip().lower()
    if name in ("openai", "openai-compat", "compat", "gpt4o", "gpt-4o", "vision"):
        try:
            return OpenAICompatVisionProvider()
        except Exception:
            return NullVisionProvider()      # key/SDK missing → graceful Null
    return NullVisionProvider()


def extract_from_photo(image_bytes: bytes, kind: str = "auto", hint: str = "") -> Dict[str, Any]:
    """Run the configured provider. Always returns a dict with 'available'."""
    try:
        out = get_provider().extract(image_bytes, kind=kind, hint=hint)
        out.setdefault("available", True)
        out.setdefault("extracted", {})
        out.setdefault("kind", kind)
        return out
    except Exception as e:
        return {"available": False, "reason": f"extraction failed: {e}", "kind": kind, "extracted": {}}


def confirm_suggestion(db, suggestion_id: int, value: Optional[str] = None,
                       run_id: Optional[int] = None, item_id: str = "", by: str = "") -> Optional[Dict[str, Any]]:
    """Operator confirms an extraction → ONLY NOW is it written to the checklist entry
    (if a target run_id+item_id is given). Never auto-committed by extract()."""
    sug = db.get_vision_suggestion(suggestion_id)
    if not sug:
        return None
    if run_id and item_id and value is not None:
        db.save_checklist_entry(int(run_id), item_id, value=str(value), status="ok", is_issue=False)
        db.set_checklist_entry_photo(int(run_id), item_id, sug["photo"])   # attach the evidence
    db.set_vision_suggestion_status(suggestion_id, "confirmed",
                                    confirmed_value=("" if value is None else str(value)))
    return db.get_vision_suggestion(suggestion_id)
