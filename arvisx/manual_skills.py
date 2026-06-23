"""C1 — turn an uploaded equipment manual into structured, GROUNDED skills.

Pipeline: stored manual file → text (pypdf / txt) → K2Think structured extraction of
{specs, PPM intervals, troubleshooting steps} → asset_knowledge store. The LLM is told to
use ONLY the manual text (no invention); without an LLM key the manual is still stored and
searchable, just not auto-distilled. The extracted PPM intervals are SUGGESTED (never
auto-applied) and the troubleshooting/specs are recalled by the agent in answers + RCA.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_MAX_CHARS = 14000           # manual text budget fed to the model (keep prompt bounded)


def extract_text(path: Path) -> str:
    """Best-effort plain text from a manual. PDF via pypdf; .txt direct; other types → ''
    (the manual is still stored/served, just not auto-distilled)."""
    if path is None or not path.is_file():
        return ""
    ext = path.suffix.lower().lstrip(".")
    if ext in ("txt", "md"):
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
    if ext == "pdf":
        try:
            from pypdf import PdfReader
        except Exception:
            return ""          # pypdf not installed → caller treats as no-text
        try:
            reader = PdfReader(str(path))
        except Exception:
            return ""
        parts = []
        for pg in reader.pages:        # per-page: one bad page must not zero the rest
            try:
                parts.append(pg.extract_text() or "")
            except Exception:
                continue
        return "\n".join(parts)
    return ""


_SYS = (
    "You extract structured maintenance knowledge from an equipment manual for a building "
    "facility team. Use ONLY the manual text provided — NEVER invent a spec, interval, or "
    "step that is not in the text. If the manual doesn't state something, omit it. Output "
    "JSON only, no prose."
)


def _interval_days(text: str) -> Optional[int]:
    """Parse a human interval ('every 3 months', 'quarterly', '500 hours') → days when it's
    clearly time-based; None otherwise (e.g. run-hours, or unparseable)."""
    t = (text or "").lower()
    for word, days in (("daily", 1), ("weekly", 7), ("fortnight", 14), ("monthly", 30),
                       ("quarterly", 90), ("half-yearly", 182), ("semi-annual", 182),
                       ("annually", 365), ("yearly", 365), ("annual", 365)):
        if word in t:
            return days
    m = re.search(r"(\d+)\s*(day|week|month|year)s?", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return n * {"day": 1, "week": 7, "month": 30, "year": 365}[unit]
    return None


async def extract_skills(llm, asset_name: str, asset_kind: str, text: str) -> Dict[str, Any]:
    """LLM structured extraction. Returns {specs, ppm, troubleshooting}; each PPM item gets a
    derived interval_days when the manual states a time interval. Empty dict if no llm/text."""
    if not llm or not text.strip():
        return {}
    body = text[:_MAX_CHARS]
    prompt = (
        f"Equipment: {asset_name} ({asset_kind or 'equipment'}).\n"
        "MANUAL TEXT (verbatim):\n\"\"\"\n" + body + "\n\"\"\"\n\n"
        "Return ONLY this JSON:\n"
        '{"specs":[{"name":"...","value":"..."}],'
        '"ppm":[{"task":"...","interval_text":"...","interval_days":null}],'
        '"troubleshooting":[{"symptom":"...","action":"..."}]}\n'
        "Include only items actually present in the text; use [] for any empty section."
    )
    try:
        out = await llm.ask_json(messages=[{"role": "user", "content": prompt}],
                                 system_msgs=[{"role": "system", "content": _SYS}],
                                 channel="extract")
    except Exception:
        return {}
    if not isinstance(out, dict):
        return {}
    specs = [s for s in (out.get("specs") or []) if isinstance(s, dict) and s.get("name")]
    trouble = [s for s in (out.get("troubleshooting") or []) if isinstance(s, dict) and s.get("symptom")]
    ppm: List[Dict[str, Any]] = []
    for p in (out.get("ppm") or []):
        if not isinstance(p, dict) or not p.get("task"):
            continue
        days = p.get("interval_days")
        if not isinstance(days, int) or days <= 0:
            days = _interval_days(str(p.get("interval_text", "")) + " " + str(p.get("task", "")))
        ppm.append({"task": p.get("task"), "interval_text": p.get("interval_text", ""),
                    "interval_days": days})
    return {"specs": specs[:40], "ppm": ppm[:40], "troubleshooting": trouble[:60]}


def knowledge_brief(knowledge: Dict[str, Any], limit: int = 6) -> str:
    """Compact, plain-text recall of an asset's manual knowledge — injected into the agent's
    context + handover so answers/RCA can cite the manual. Empty string when nothing stored."""
    if not knowledge:
        return ""
    specs = knowledge.get("specs") or []
    ppm = knowledge.get("ppm") or []
    tr = knowledge.get("troubleshooting") or []
    parts: List[str] = []
    if specs:
        parts.append("specs: " + "; ".join(f"{s['name']}={s.get('value','')}" for s in specs[:limit]))
    if ppm:
        parts.append("PPM: " + "; ".join(
            f"{p['task']} ({p.get('interval_text') or (str(p['interval_days'])+'d' if p.get('interval_days') else '?')})"
            for p in ppm[:limit]))
    if tr:
        parts.append("troubleshooting: " + "; ".join(f"{t['symptom']}→{t.get('action','')}" for t in tr[:limit]))
    return " | ".join(parts)
