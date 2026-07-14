"""
Worker 2 — the estimator. Deterministic. No LLM touches a rupee.

Every number here comes from the rate card (seeds/pricing_*.json). The AI's only job upstream
was to COUNT what's in the house (Worker 1); pricing is arithmetic over a table a human owns and
can retune. That separation is the whole trick: a wrong count is a visible, correctable mistake;
an invented price is a lie you can't see.

Confidence is honest and mechanical: it falls when we had to ASSUME a quantity rather than read
it, and when the floor plan gave us little to go on. It is never rounded up to look good.

The budget NEVER changes the estimate. It only decides which of four things we say afterwards.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_SEED = Path(__file__).parent / "seeds" / "pricing_bangalore.json"

TIERS = ("basic", "good", "premium", "luxury")


def load_rates(path: Optional[Path] = None) -> Dict[str, Any]:
    return json.loads((path or _SEED).read_text(encoding="utf-8"))


def lakhs(rupees: float) -> str:
    """₹18,43,000 → '₹18.4 Lakhs' — the only format anyone in India actually reads."""
    return f"₹{rupees / 100000:.1f} Lakhs"


def estimate(scope: Dict[str, Any], tier: str, rates: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """scope = {"items": [{"key","qty","assumed":bool}], "rooms": {...}} from Worker 1.
    Returns line items, subtotal, overheads, total, and an honest confidence."""
    rc = rates or load_rates()
    tier = tier if tier in TIERS else "good"
    catalog = rc["items"]
    lines: List[Dict[str, Any]] = []
    assumed_count = 0

    for it in scope.get("items", []):
        key = it.get("key")
        spec = catalog.get(key)
        if not spec:
            continue                                  # unknown item → priced at zero, never guessed
        qty = it.get("qty")
        assumed = bool(it.get("assumed"))
        if qty in (None, "", 0):
            qty = spec["typical_qty"]
            assumed = True
        if assumed:
            assumed_count += 1
        rate = float(spec["rates"][tier])
        cost = round(float(qty) * rate)
        lines.append({"key": key, "label": spec["label"], "unit": spec["unit"],
                      "qty": qty, "rate": rate, "cost": cost, "assumed": assumed})

    subtotal = sum(line["cost"] for line in lines)
    ov = rc["overheads"]
    design = round(subtotal * ov["design_fee_pct"] / 100)
    execution = round(subtotal * ov["execution_pct"] / 100)
    pre_tax = subtotal + design + execution
    gst = round(pre_tax * ov["gst_pct"] / 100)
    total = pre_tax + gst

    return {
        "tier": tier,
        "lines": lines,
        "subtotal": subtotal,
        "design_fee": design,
        "execution": execution,
        "gst": gst,
        "total": total,
        "total_pretty": lakhs(total),
        "confidence": confidence(scope, lines, assumed_count),
    }


def confidence(scope: Dict[str, Any], lines: List[Dict[str, Any]], assumed_count: int) -> int:
    """How much of this did we actually READ, versus assume?

    Starts from the vision's own confidence in the takeoff, then docks points for every quantity
    we had to fall back to a typical value for. Floors at 40 — we never pretend to be sure, and
    never claim more than 95 because a floor plan is not a site visit."""
    base = float(scope.get("vision_confidence") or 0.0)
    if not lines:
        return 40
    if base <= 0:                                     # scope came from the user, not a floor plan
        base = 0.85 if scope.get("source") == "user" else 0.6
    assumed_ratio = assumed_count / len(lines)
    score = base * 100 - (assumed_ratio * 35)
    if len(lines) < 4:                                # a suspiciously bare plan
        score -= 8
    return int(max(40, min(95, round(score))))


# ── budget: changes the MESSAGE, never the ESTIMATE ───────────────────────
def budget_band(band_id: str, rates: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    rc = rates or load_rates()
    return next((b for b in rc["budget_bands"] if b["id"] == band_id), None)


def budget_reference(band: Dict[str, Any]) -> float:
    """What the person actually MEANT when they tapped a band.

    Someone who picks "₹20–30L" means about ₹25L, not ₹20L — so a ₹18L estimate genuinely leaves
    them headroom, and telling them it's "about right" would be a lie of framing. Open-ended bands
    have only one honest anchor: "under ₹10L" means the ceiling, "above ₹30L" means the floor."""
    lo, hi = float(band["min"]), float(band["max"])
    if lo <= 0:                       # "under ₹10L" → the ceiling is the budget
        return hi
    if hi >= 9e7:                     # "above ₹30L" → the floor is the budget
        return lo
    return (lo + hi) / 2.0            # a range means the middle of it


def budget_verdict(total: float, band_id: str, rates: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """The four situations. The estimate is already fixed by this point — this only picks words."""
    rc = rates or load_rates()
    band = budget_band(band_id, rc)
    if not band or band["min"] is None:
        return {
            "situation": "unknown",
            "text": ("Here's a realistic estimate — use it as a starting point for planning. "
                     "When you have a budget in mind, we can shape the design around it."),
        }
    ref = budget_reference(band)
    tol = rc.get("close_tolerance_pct", 12.0) / 100.0

    if total > ref * (1 + tol):
        return {
            "situation": "over",
            "text": (f"Your dream home comes to about {lakhs(total - ref)} more than your planned "
                     f"budget.\nThat's normal — and fixable. We can bring it down by changing "
                     f"materials, trimming the scope, or phasing the work."),
        }
    if total < ref * (1 - tol):
        return {
            "situation": "under",
            "text": (f"Good news — you're comfortably inside your budget, with roughly "
                     f"{lakhs(ref - total)} of headroom.\nYou could upgrade finishes or add "
                     f"pieces without stretching."),
        }
    return {
        "situation": "close",
        "text": ("Your budget and this estimate line up well. That's the best place to start "
                 "from — expectations and cost are in the same room."),
    }
