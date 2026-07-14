"""
Worker 1 — the takeoff. Floor plan → "what has to be built in this house".

This is the ONE place in the product where we look at an image and interpret it. (The AI Manager
deliberately does the opposite: it asks a human what a site photo shows.) The difference is that
a floor plan is a *document* — it exists to be read — whereas a site photo is a moment that only
the person standing there can explain.

Hard boundary: this worker COUNTS. It never prices. It returns rooms and a list of items with
quantities, and it says how sure it is. Pricing is Worker 2's arithmetic over a rate card a human
owns. A miscount is a visible, correctable mistake; an invented price is a lie you can't see.

No vision model configured → we do not guess at the drawing. We ask the human the four questions
that actually drive the number (BHK, bathrooms, balconies, carpet area) and build the scope from
their answers, flagged honestly as `source: user`.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("fbq.takeoff")

# provider → (key_env, default_base_url, default_model)
VISION_PROVIDERS = {
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o-mini"),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "meta-llama/llama-4-scout-17b-16e-instruct"),
    "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash"),
}

_TAKEOFF_SYS = (
    "You read an apartment FLOOR PLAN and list what interior work it implies. You are a quantity "
    "surveyor, not a salesperson: COUNT things, never price them.\n"
    "Identify the rooms (bedrooms, bathrooms, kitchen, living, dining, balconies) and the carpet "
    "area in sqft if any dimensions or a total are printed on the drawing.\n"
    "Then list the interior items the home needs, using ONLY these keys: modular_kitchen, "
    "wardrobe, tv_unit, false_ceiling, painting, vanity, shoe_rack, crockery_unit, pooja_unit, "
    "study_table, bed, dining, foyer_unit, balcony.\n"
    "Give a quantity for each: sqft for modular_kitchen / wardrobe / tv_unit / false_ceiling / "
    "painting, and a count for the rest (e.g. 3 wardrobes for a 3BHK, one vanity per bathroom).\n"
    "If the drawing does not let you size something, set qty to null and assumed to true — do NOT "
    "invent a number. If you cannot read the image as a floor plan at all, return "
    '{"readable": false}.\n'
    'Output JSON only: {"readable": true, "rooms": {"bedrooms": n, "bathrooms": n, "balconies": n, '
    '"kitchen": true, "living": true, "carpet_sqft": n or null}, "items": [{"key": "...", '
    '"qty": n or null, "assumed": true|false}], "confidence": 0.0-1.0}'
)


def _vision_config():
    prov = (os.environ.get("FBQ_VISION_PROVIDER", "openai") or "openai").strip().lower()
    key_env, base, model = VISION_PROVIDERS.get(prov, VISION_PROVIDERS["openai"])
    return (prov,
            os.environ.get("FBQ_VISION_BASE_URL") or base,
            os.environ.get("FBQ_VISION_KEY") or os.environ.get(key_env, ""),
            os.environ.get("FBQ_VISION_MODEL") or model)


def vision_available() -> bool:
    return bool(_vision_config()[2])


def read_floor_plan(image: bytes, mime: str = "image/jpeg") -> Optional[Dict[str, Any]]:
    """Floor plan → scope. None when no vision model is configured or the call fails; {"readable":
    False} when the model looked and couldn't make sense of it. Both are handled by asking the
    human — neither is ever papered over with a guess."""
    prov, base, key, model = _vision_config()
    if not key or not image:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=base, timeout=90.0, max_retries=1)
        b64 = base64.b64encode(image).decode("ascii")
        resp = client.chat.completions.create(
            model=model, temperature=0,
            messages=[
                {"role": "system", "content": _TAKEOFF_SYS},
                {"role": "user", "content": [
                    {"type": "text", "text": "Read this floor plan and list the interior scope."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ]},
            ])
        raw = (resp.choices[0].message.content or "") if resp.choices else ""
    except Exception as e:
        logger.warning(f"[takeoff:{prov}] vision call failed: {e}")
        return None

    data = _extract_json(raw)
    if not isinstance(data, dict):
        return None
    if not data.get("readable", True):
        return {"readable": False}
    return normalise(data, source="vision")


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    s = text.strip()
    if "```" in s:
        m = re.search(r"```(?:json)?\s*(.+?)```", s, re.S)
        if m:
            s = m.group(1).strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


_VALID = {"modular_kitchen", "wardrobe", "tv_unit", "false_ceiling", "painting", "vanity",
          "shoe_rack", "crockery_unit", "pooja_unit", "study_table", "bed", "dining",
          "foyer_unit", "balcony"}


def normalise(data: Dict[str, Any], source: str = "vision") -> Dict[str, Any]:
    """Keep only known items, coerce types, and never let a hallucinated key through."""
    rooms = data.get("rooms") or {}
    items: List[Dict[str, Any]] = []
    for it in data.get("items", []):
        key = str(it.get("key", "")).strip()
        if key not in _VALID:
            continue
        qty = it.get("qty")
        try:
            qty = float(qty) if qty not in (None, "", "null") else None
        except (TypeError, ValueError):
            qty = None
        items.append({"key": key, "qty": qty,
                      "assumed": bool(it.get("assumed")) or qty is None})
    return {
        "readable": True,
        "source": source,
        "rooms": {
            "bedrooms": int(rooms.get("bedrooms") or 0),
            "bathrooms": int(rooms.get("bathrooms") or 0),
            "balconies": int(rooms.get("balconies") or 0),
            "kitchen": bool(rooms.get("kitchen", True)),
            "living": bool(rooms.get("living", True)),
            "carpet_sqft": rooms.get("carpet_sqft"),
        },
        "items": items,
        "vision_confidence": float(data.get("confidence") or 0.0) if source == "vision" else 0.0,
    }


# ── the fallback: build the scope from what the human tells us ────────────
def scope_from_answers(bedrooms: int, bathrooms: int = 0, balconies: int = 0,
                       carpet_sqft: Optional[float] = None) -> Dict[str, Any]:
    """No vision (or an unreadable drawing) → the four questions that actually move the number.
    Quantities that follow from the BHK are real; the rest are flagged `assumed` so confidence
    reflects the truth."""
    bedrooms = max(1, int(bedrooms or 1))
    bathrooms = int(bathrooms or max(1, bedrooms - 1))
    balconies = int(balconies or 1)
    area = float(carpet_sqft) if carpet_sqft else None

    items: List[Dict[str, Any]] = [
        {"key": "modular_kitchen", "qty": None, "assumed": True},
        {"key": "wardrobe", "qty": None, "assumed": True, "count": bedrooms},
        {"key": "bed", "qty": bedrooms, "assumed": False},
        {"key": "tv_unit", "qty": None, "assumed": True},
        {"key": "vanity", "qty": bathrooms, "assumed": False},
        {"key": "balcony", "qty": balconies, "assumed": False},
        {"key": "shoe_rack", "qty": 1, "assumed": False},
        {"key": "dining", "qty": 1, "assumed": False},
        {"key": "false_ceiling", "qty": (area * 0.45) if area else None, "assumed": area is None},
        {"key": "painting", "qty": (area * 2.8) if area else None, "assumed": area is None},
    ]
    # wardrobes scale with bedrooms: express as sqft (typical per-wardrobe × count)
    for it in items:
        if it["key"] == "wardrobe":
            it["qty"] = 42.0 * bedrooms          # typical_qty in the rate card is per wardrobe
            it["assumed"] = True
            it.pop("count", None)

    return {
        "readable": True,
        "source": "user",
        "rooms": {"bedrooms": bedrooms, "bathrooms": bathrooms, "balconies": balconies,
                  "kitchen": True, "living": True, "carpet_sqft": area},
        "items": items,
        "vision_confidence": 0.0,
    }


def scale_for_rooms(scope: Dict[str, Any]) -> Dict[str, Any]:
    """A 3BHK needs three wardrobes and three beds. If the vision named the rooms but left the
    per-bedroom items at a single unit, scale them — using the ROOM COUNT it actually read, not
    an invention."""
    rooms = scope.get("rooms") or {}
    beds = int(rooms.get("bedrooms") or 0)
    baths = int(rooms.get("bathrooms") or 0)
    balc = int(rooms.get("balconies") or 0)
    per_room = {"bed": beds, "vanity": baths, "balcony": balc}
    for it in scope.get("items", []):
        n = per_room.get(it["key"])
        if n and (it.get("qty") in (None, 0, 1)):
            it["qty"] = float(n)
            it["assumed"] = False
        if it["key"] == "wardrobe" and beds and (it.get("qty") in (None, 0)):
            it["qty"] = 42.0 * beds
            it["assumed"] = True
    return scope


def summarise(scope: Dict[str, Any]) -> List[str]:
    """The '✅ Kitchen / ✅ Wardrobes' list the user actually sees. No numbers — those come later."""
    from fbq.pricing import load_rates
    cat = load_rates()["items"]
    seen, out = set(), []
    for it in scope.get("items", []):
        label = cat.get(it["key"], {}).get("label")
        if label and label not in seen:
            seen.add(label)
            out.append(label)
    return out
