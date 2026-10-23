"""
Verified repairs become the building's knowledge — and that knowledge matures.

The diagnosis KB learns per rule from re-checked repairs (learn_from_verification).
This makes the same outcome a *building skill* the agents can recall:

  first verified repair of (rule, cause, equipment)
      → skill "AHU-07 Supply air above setpoint: chilled-water valve not opening"
  every re-checked repair of the same (rule, cause, equipment) after that
      → BuildingSkillbook.verify_skill(…, worked) — Bayesian confidence; ACTIVE after
        repeated confirmation, DEPRECATED if fixes of that cause keep failing.

A failed repair never creates a lesson on its own (that would teach the wrong
cause). skill_links maps (rule, cause, equipment) → skill so outcomes always update
the same skill instead of creating near-duplicates.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("arvis.fdd.lessons")

_DDL = "CREATE TABLE IF NOT EXISTS skill_links (key TEXT PRIMARY KEY, skill_id TEXT NOT NULL, created_at TEXT)"


async def apply_verification(database: Any, skillbook: Any, v: Any) -> Optional[Dict[str, Any]]:
    """Turn one decided repair verification into (or onto) a building skill."""
    if getattr(v, "status", None) not in ("verified", "failed") or not getattr(v, "hypothesis", None):
        return None
    from agent_commercial.fdd import RULES_BY_ID
    from agent_commercial.fdd.diagnosis import load_kb
    kb = await load_kb(database, v.rule_id)
    hid = kb.match_hypothesis(v.hypothesis)
    if hid is None:
        return {"skipped": f"cause {v.hypothesis!r} is not one of {v.rule_id}'s modelled causes"}
    label = kb.hypothesis(hid).label
    key = f"{v.rule_id}|{hid}|{v.equipment_id}"
    conn = await database._get_async_connection()
    await conn.execute(_DDL)
    async with conn.execute("SELECT skill_id FROM skill_links WHERE key=?", (key,)) as cur:
        row = await cur.fetchone()
    worked = v.status == "verified"
    created = False
    if row is None:
        if not worked:
            return {"skipped": "a failed repair does not create a lesson"}
        rule = RULES_BY_ID.get(v.rule_id)
        title = f"{v.equipment_id} {rule.title if rule else v.rule_id}: {label}"
        skills = await skillbook.add_skill(
            skill_type="fault_pattern", title=title,
            description=(f"On {v.equipment_id}, '{rule.title if rule else v.rule_id}' ({v.rule_id}) was fixed by "
                         f"addressing: {label}. Confirmed by ARVIS's re-check after the repair of {v.repaired_at}."),
            equipment_id=v.equipment_id, confidence=0.6, created_by="closed_loop",
            evidence={"verification_id": v.id, "rule_id": v.rule_id, "hypothesis_id": hid,
                      "work_order_id": getattr(v, "work_order_id", None)},
            context_signature={"rule_id": v.rule_id, "hypothesis_id": hid}, auto_chunk=False)
        skill_id = skills[0].skill_id
        await conn.execute("INSERT INTO skill_links (key, skill_id, created_at) VALUES (?,?,?)",
                           (key, skill_id, datetime.now().isoformat(timespec="seconds")))
        await conn.commit()
        created = True
    else:
        skill_id = row[0]
    await skillbook.verify_skill(skill_id, worked)
    logger.info(f"[Lessons] {key}: repair {'worked' if worked else 'failed'} → skill {skill_id}"
                f"{' (new)' if created else ''}")
    return {"skill_id": skill_id, "created": created, "worked": worked, "cause": label}
