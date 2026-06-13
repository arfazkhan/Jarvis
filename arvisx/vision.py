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

import os
from typing import Any, Dict, Optional


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


_PROVIDER: Optional[VisionProvider] = None


def register_vision_provider(provider: VisionProvider) -> None:
    """Plug in a real multimodal model (Claude/GPT-4o/etc.) at runtime. The provider only
    needs extract(image_bytes, kind, hint) -> {"available":True,"extracted":{...},...}."""
    global _PROVIDER
    _PROVIDER = provider


def get_provider() -> VisionProvider:
    if _PROVIDER is not None:
        return _PROVIDER
    # Future: build a provider from ARVISX_VISION_PROVIDER here. Until one is wired, Null.
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
