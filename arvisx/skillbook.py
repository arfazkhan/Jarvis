"""
ArvisX skillbook (Phase 7) — institutional memory.

Learns fault patterns per equipment class so the building gets smarter over time and
knowledge survives staff turnover. A skill = (scope, symptom) → cause + action, with a
times_seen counter and a CONFIRMED flag set when a vendor/operator closes a work order
with the actual cause. On a new risk, recall() surfaces a matching prior skill — "seen
before: high current → bearing wear (vendor-confirmed 2026-03-12)" — which the grounded
advisory leads with.

Honesty preserved: recall only returns what was actually recorded (no invention); an
unconfirmed skill is surfaced as a prior, a confirmed one as established. scope =
equipment class (AssetType) so a lesson learned on one pump applies to all of them.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Optional

from arvisx.models import Asset, Risk


def symptom_of(risk: Risk) -> str:
    """Normalized symptom key from a risk message (asset name stripped, numbers
    generalized) — the same standing problem maps to one skill."""
    stem = risk.message.replace(risk.asset_name, "").strip().lower()
    stem = re.sub(r"\d+(\.\d+)?", "#", stem)
    return re.sub(r"\s+", " ", stem).strip(" -:")


class Skillbook:
    def __init__(self, db):
        self.db = db   # ArvisxDb

    def record(self, asset: Asset, risk: Risk, cause: str, action: str,
               confirmed: bool = False, source: str = "auto") -> None:
        self._upsert(asset.asset_type.value, symptom_of(risk), cause, action, confirmed, source)

    def record_confirmed(self, scope: str, symptom: str, cause: str, action: str,
                         source: str = "vendor") -> None:
        """Outcome feedback: a vendor/operator closed a ticket with the actual cause."""
        self._upsert(scope, symptom, cause, action, confirmed=True, source=source)

    def _upsert(self, scope: str, sym: str, cause: str, action: str,
                confirmed: bool, source: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.db._lock, self.db._conn() as c:
            row = c.execute("SELECT times_seen, confirmed, confidence FROM skills "
                            "WHERE building_id=? AND scope=? AND symptom=?",
                            (self.db.building_id, scope, sym)).fetchone()
            if row:
                times = row["times_seen"] + 1
                # confidence grows with repetition; a confirmation pins it high.
                conf = 0.9 if (confirmed or row["confirmed"]) else min(0.85, 0.4 + 0.1 * times)
                c.execute("UPDATE skills SET times_seen=?, confirmed=?, confidence=?, last_seen=?, "
                          "cause=COALESCE(NULLIF(?, ''), cause), action=COALESCE(NULLIF(?, ''), action), source=? "
                          "WHERE building_id=? AND scope=? AND symptom=?",
                          (times, 1 if (confirmed or row["confirmed"]) else 0, conf, now,
                           cause if confirmed else "", action if confirmed else "",
                           source if confirmed else "auto",
                           self.db.building_id, scope, sym))
            else:
                conf = 0.9 if confirmed else 0.4
                c.execute("INSERT INTO skills (building_id, scope, symptom, cause, action, confidence, "
                          "times_seen, confirmed, last_seen, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (self.db.building_id, scope, sym, cause, action, conf, 1,
                           1 if confirmed else 0, now, source))

    def recall(self, asset: Asset, risk: Risk) -> Optional[Dict[str, Any]]:
        """Return a prior learned skill matching this asset class + symptom, if any."""
        scope = asset.asset_type.value
        sym = symptom_of(risk)
        with self.db._lock, self.db._conn() as c:
            row = c.execute("SELECT * FROM skills WHERE building_id=? AND scope=? AND symptom=?",
                            (self.db.building_id, scope, sym)).fetchone()
            return dict(row) if row else None

    def all(self) -> list:
        with self.db._lock, self.db._conn() as c:
            rows = c.execute("SELECT * FROM skills WHERE building_id=? ORDER BY confirmed DESC, times_seen DESC",
                             (self.db.building_id,)).fetchall()
            return [dict(r) for r in rows]

    def recall_note(self, asset: Asset, risk: Risk) -> Optional[str]:
        """Human-readable institutional-memory line for the advisory."""
        s = self.recall(asset, risk)
        if not s:
            return None
        if s["confirmed"]:
            return (f"Institutional memory: this symptom on {asset.asset_type.value} was previously "
                    f"CONFIRMED as '{s['cause']}' (seen {s['times_seen']}×, last {s['last_seen'][:10]}). "
                    f"Likely the same — {s['action']}")
        return (f"Seen before: similar symptom recorded {s['times_seen']}× on this equipment class "
                f"(unconfirmed prior). Candidate cause: {s['cause']}")
