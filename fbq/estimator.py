"""
Agent 2 — the Cost Estimator conversation.

Three taps and a floor plan:

    upload plan  →  pick a style  →  pick a budget  →  estimate  →  talk to an expert?

A small explicit state machine, because a funnel that silently loses people is worse than no
funnel. Every step knows what it's waiting for and says so.

The business goal is the LEAD: by the time a human designer picks up the phone, we already know
the home, the taste and the money. The estimate is what we give in exchange for that.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fbq import pricing, takeoff

# where a lead is in the funnel
STAGES = ("new", "awaiting_plan", "awaiting_rooms", "awaiting_tier", "awaiting_budget",
          "estimated", "lead_captured", "declined")

TIER_WORDS = {
    "1": "basic", "basic": "basic",
    "2": "good", "good": "good",
    "3": "premium", "premium": "premium",
    "4": "luxury", "luxury": "luxury",
}


def greeting() -> str:
    return ("👋 Hi! I can give you a realistic estimate for your home interiors in about 2 minutes.\n\n"
            "*Send me your floor plan* — a photo, a screenshot or a PDF is fine.\n"
            "_No floor plan handy? Just tell me the BHK (e.g. \"3bhk\") and I'll work from that._")


def ask_tier() -> str:
    rc = pricing.load_rates()
    L = ["*What kind of interiors are you after?*\n"]
    for i, key in enumerate(pricing.TIERS, 1):
        t = rc["tiers"][key]
        L.append(f"*{i}. {t['label']}* — {t['blurb']}")
    L.append("\n_Reply with 1, 2, 3 or 4._")
    return "\n".join(L)


def ask_budget() -> str:
    rc = pricing.load_rates()
    L = ["*And roughly what budget do you have in mind?*\n"]
    for i, b in enumerate(rc["budget_bands"], 1):
        L.append(f"*{i}.* {b['label']}")
    L.append("\n_Reply with a number. This won't change your estimate — it just helps me "
             "give you the right advice._")
    return "\n".join(L)


def ask_rooms() -> str:
    return ("I couldn't read that as a floor plan — no problem, I won't guess. 🙂\n\n"
            "*Just tell me the basics:* how many bedrooms, bathrooms and balconies?\n"
            "_e.g. \"3 bed, 2 bath, 2 balcony\" — or simply \"3bhk\"._")


def parse_tier(text: str) -> Optional[str]:
    t = (text or "").strip().lower()
    return TIER_WORDS.get(t) or next(
        (v for k, v in TIER_WORDS.items() if k.isalpha() and k in t), None)


def parse_budget(text: str) -> Optional[str]:
    """Accepts '3' (the option number) or words like 'under 10' / 'not sure'."""
    rc = pricing.load_rates()
    bands = rc["budget_bands"]
    t = (text or "").strip().lower()
    if t.isdigit():
        i = int(t) - 1
        if 0 <= i < len(bands):
            return bands[i]["id"]
    if any(w in t for w in ("not sure", "dunno", "no idea", "unsure", "don't know", "dont know")):
        return "unsure"
    nums = [int(n) for n in re.findall(r"\d+", t)]
    if nums:
        # "15-20", "around 18 lakhs", "18L"
        val = max(nums) * (100000 if max(nums) < 200 else 1)
        for b in bands:
            if b["min"] is not None and b["min"] <= val <= b["max"]:
                return b["id"]
    return None


_BHK = re.compile(r"(\d+)\s*(?:bhk|bed(?:room)?s?)", re.I)
_BATH = re.compile(r"(\d+)\s*(?:bath(?:room)?s?|toilets?)", re.I)
_BALC = re.compile(r"(\d+)\s*balcon", re.I)
_AREA = re.compile(r"(\d{3,5})\s*(?:sq\.?\s?ft|sqft|sft)", re.I)


def parse_rooms(text: str) -> Optional[Dict[str, Any]]:
    """'3 bed, 2 bath, 2 balcony, 1200 sqft' / '3bhk' → the four numbers that move the estimate."""
    t = text or ""
    m = _BHK.search(t)
    if not m:
        return None
    beds = int(m.group(1))
    if not (1 <= beds <= 8):
        return None
    b = _BATH.search(t)
    bl = _BALC.search(t)
    a = _AREA.search(t)
    return {"bedrooms": beds,
            "bathrooms": int(b.group(1)) if b else 0,
            "balconies": int(bl.group(1)) if bl else 0,
            "carpet_sqft": float(a.group(1)) if a else None}


def wants_expert(text: str) -> Optional[bool]:
    t = (text or "").strip().lower()
    if re.match(r"^(yes|y|yeah|sure|ok(ay)?|please|haan|ha)\b", t):
        return True
    if re.match(r"^(no|n|nope|not now|later|nahi)\b", t):
        return False
    return None


# ── the result the user actually reads ────────────────────────────────────
def render_estimate(scope: Dict[str, Any], est: Dict[str, Any], verdict: Dict[str, str],
                    tier_label: str) -> str:
    items = takeoff.summarise(scope)
    L = ["*Your home includes*"]
    L += [f"✅ {i}" for i in items[:10]]
    L.append("")
    L.append(f"*Estimated cost*\n{est['total_pretty']}  _({tier_label} finish, incl. GST)_")
    L.append(f"\n*Confidence*  {est['confidence']}%")
    if est["confidence"] < 70:
        L.append("_Some quantities were assumed — a designer will firm these up._")
    L.append("")
    L.append(verdict["text"])
    L.append("\n👉 *Would you like to talk to an interior expert?* (yes / no)")
    return "\n".join(L)


def breakdown(est: Dict[str, Any]) -> str:
    """Only if they ask for it — the estimate stays simple by default."""
    L = ["*Where the money goes*"]
    for line in sorted(est["lines"], key=lambda x: -x["cost"]):
        if line["cost"] <= 0:
            continue
        tag = " _(assumed)_" if line["assumed"] else ""
        L.append(f"• {line['label']}: {pricing.lakhs(line['cost'])}{tag}")
    L.append(f"\nSubtotal: {pricing.lakhs(est['subtotal'])}")
    L.append(f"Design + execution: {pricing.lakhs(est['design_fee'] + est['execution'])}")
    L.append(f"GST: {pricing.lakhs(est['gst'])}")
    L.append(f"*Total: {est['total_pretty']}*")
    return "\n".join(L)
