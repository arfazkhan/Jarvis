"""
Numeric Audit — Deterministic Synthesis Output Verifier
=======================================================

Stops the H4 correction loop by catching hallucinated numbers BEFORE the
faithfulness LLM is invoked.

Why this exists:
    Marina S1 runs consistently saw synthesis output assert numeric values
    (COP=6.855, CH-01 load 90.7%, "12,386 points", "13.63°C") that were not
    in the evidence ledger. H4 (LLM-based faithfulness verifier) caught these
    as contradictions, burned 30-70s on correction LLM + re-verification,
    and frequently failed on the second pass anyway. Net: every T2 turn paid
    ~70s tax for the same class of hallucination.

This module replaces that loop with a deterministic check:
    1. Pre-synthesis: walk plan.evidence + LIVE_BMS_SNAPSHOT, extract every
       numeric token into AllowedNumberSet with source attribution.
    2. Post-synthesis: regex-scan advisory text for numeric tokens.
    3. For each output number, check if it matches any allowed value within
       a small tolerance (2% relative or 0.5 absolute for near-zero).
    4. Orphans (numbers with no match) → replaced with `[unverified]` token
       in the message text. NO LLM call. ~5ms per audit.
    5. If audit found zero orphans, H4 can be safely skipped on this turn —
       caller decides based on AuditReport.fully_clean.

Public API:
    auditor = NumericAuditor()
    allowed = auditor.extract_allowed_numbers(plan, context)
    report  = auditor.audit_advisory_json(advisory_str, allowed)
    sanitized = auditor.strip_orphans(advisory_str, report)
"""
from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("arvis.swarm.numeric_audit")


# Match any standalone number — integer or decimal, optional sign, optional comma
# thousands separator. Excludes numbers inside identifiers like "CH-01" or
# "2026-05-25" via the preceding/following char constraints in _is_real_number.
_NUMERIC_RE = re.compile(
    r"(?<![A-Za-z_])"             # not preceded by alphanumeric (excludes CH-01)
    r"(-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)"
    r"(?![A-Za-z_])"              # not followed by alphanumeric
)

# Patterns we should NEVER treat as orphans even when unmatched
_NUMERIC_WHITELIST_CONTEXT = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),                        # dates
    re.compile(r"\b\d{2}:\d{2}(?::\d{2})?\b"),                   # times
    re.compile(r"\b(?:CH|AHU|VAV|FCU|CT|CHWP|CDWP|ZONE|FLOOR|METER|PCHWP|SCHWP)-\d+[A-Z]?\b"),  # equipment IDs
    re.compile(r"\b(?:GSAS|ASHRAE|NFPA|QCS)\s*\d+(?:[\.\-]\d+)*\b"),  # standards refs
    re.compile(r"\b(?:cluster|alarm|run|plan|advisory|turn|page|fig(?:ure)?)\s*[\#:]?\s*\d+\b", re.IGNORECASE),
    re.compile(r"\b\d{4,}[a-f0-9]{4,}\b"),                       # ULIDs / evidence IDs
]


@dataclass(frozen=True)
class AllowedNumber:
    value: float
    source_id: str         # evidence_id or "snapshot:eq_id:point_name"
    label: str             # human-friendly description for debugging


@dataclass
class AllowedNumberSet:
    items: List[AllowedNumber] = field(default_factory=list)

    def values(self) -> List[float]:
        return [a.value for a in self.items]

    def add(self, value: float, source_id: str, label: str) -> None:
        # Skip absurdly long noise from JSON dumps
        if abs(value) > 1e12:
            return
        self.items.append(AllowedNumber(value=value, source_id=source_id, label=label))

    def __len__(self) -> int:
        return len(self.items)


@dataclass
class NumericMatch:
    output_value: float
    matched_to: Optional[AllowedNumber]
    surface_form: str          # original token as it appeared in the advisory
    span: Tuple[int, int]      # (start, end) in scanned text
    context_field: str         # "message" | "analysis" | "impact"


@dataclass
class AuditReport:
    total_numbers: int = 0
    matched: List[NumericMatch] = field(default_factory=list)
    orphans: List[NumericMatch] = field(default_factory=list)

    @property
    def fully_clean(self) -> bool:
        return self.total_numbers > 0 and len(self.orphans) == 0

    @property
    def orphan_count(self) -> int:
        return len(self.orphans)

    def summary(self) -> str:
        return (
            f"NumericAudit: total={self.total_numbers} matched={len(self.matched)} "
            f"orphans={len(self.orphans)}"
        )


# Tolerance config — separate bands for different magnitudes
_DEFAULT_REL_TOLERANCE = 0.02       # 2% for values |v| >= 10
_DEFAULT_ABS_TOLERANCE_SMALL = 0.5  # for values where relative would be too tight
_SMALL_MAGNITUDE_THRESHOLD = 10.0


def _numbers_match(output: float, allowed: float) -> bool:
    """Check if output ≈ allowed within tolerance."""
    # Exact match always wins
    if output == allowed:
        return True
    diff = abs(output - allowed)
    mag = max(abs(output), abs(allowed))
    if mag < _SMALL_MAGNITUDE_THRESHOLD:
        return diff <= _DEFAULT_ABS_TOLERANCE_SMALL
    return (diff / mag) <= _DEFAULT_REL_TOLERANCE


def _parse_number(token: str) -> Optional[float]:
    """Parse a numeric token (handles comma thousands separators)."""
    try:
        return float(token.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _is_whitelisted_context(text: str, start: int, end: int) -> bool:
    """Check if the number sits inside a date / equipment ID / cluster ref / etc."""
    # Scan a small window around the token (15 chars each side)
    win_start = max(0, start - 15)
    win_end = min(len(text), end + 15)
    window = text[win_start:win_end]
    for pat in _NUMERIC_WHITELIST_CONTEXT:
        if pat.search(window):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# NumericAuditor
# ─────────────────────────────────────────────────────────────────────────────

class NumericAuditor:
    """Deterministic synthesis-output number validator. Zero LLM calls."""

    # ── extract allowed numbers ────────────────────────────────────────

    def extract_allowed_numbers(
        self,
        plan: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> AllowedNumberSet:
        """
        Walk plan.evidence + LIVE_BMS_SNAPSHOT + grounding context, collect
        every numeric value into an AllowedNumberSet.

        Sources (in priority order):
          1. plan.evidence — each Evidence.raw_payload scanned for numbers
          2. context["LIVE_BMS_SNAPSHOT"] — per-equipment points + weather + meters
          3. context["GROUNDING_ALARMS"] — alarm metadata
          4. context["TERMINAL_ADVISORIES_PENDING"] — prior fired numbers carried forward
          5. context["PRIOR_TURN_FINDINGS"] — prior turn cited numbers
        """
        allowed = AllowedNumberSet()

        # 1. Evidence ledger
        try:
            evidence = getattr(plan, "evidence", None)
            if evidence is not None:
                # plan.evidence may be a custom collection — try .get_all() then iter
                items = []
                if hasattr(evidence, "get_all"):
                    items = evidence.get_all()
                elif hasattr(evidence, "items"):
                    items = list(evidence.items)
                else:
                    try:
                        items = list(evidence)
                    except Exception:
                        items = []
                for ev in items:
                    eid = str(getattr(ev, "id", "ev?"))
                    label = str(getattr(ev, "source_tool", "evidence"))
                    payload = getattr(ev, "raw_payload", None)
                    if payload is None:
                        continue
                    self._scrape_numbers(payload, eid, label, allowed, max_depth=6)
        except Exception as e:
            logger.debug(f"[NumericAudit] evidence scrape failed: {e}")

        # 2. LIVE_BMS_SNAPSHOT (deep) — this is usually the largest source
        if context:
            snap = context.get("LIVE_BMS_SNAPSHOT")
            if isinstance(snap, dict):
                # Walk the whole snapshot
                self._scrape_numbers(snap, "snapshot", "live_snapshot", allowed, max_depth=8)
            # 3. Alarms
            for alm in (context.get("GROUNDING_ALARMS") or [])[:50]:
                self._scrape_numbers(alm, "alarm", "alarms", allowed, max_depth=4)
            # 4. Terminal advisories pending — carry forward prior numerics
            for t in (context.get("TERMINAL_ADVISORIES_PENDING") or []):
                self._scrape_numbers(t, t.get("advisory_id", "term"), "terminal_advisory", allowed, max_depth=4)
            # 5. Prior turn findings — already-cited numbers stay legal
            for t in (context.get("PRIOR_TURN_FINDINGS") or []):
                self._scrape_numbers(t, f"prior_turn_{t.get('turn_idx', '?')}", "prior_turn", allowed, max_depth=5)
            # 6. Cross-agent findings (tool results aggregated by Queen)
            for k, v in (context.get("cross_agent_findings") or {}).items():
                self._scrape_numbers(v, f"cross:{k}", "cross_agent", allowed, max_depth=5)

        # Fix 1c: cap at 5000 via seeded random sampling to bound prompt size
        if len(allowed) > 5000:
            _orig_n = len(allowed)
            _rng = random.Random(42)
            allowed.items = _rng.sample(allowed.items, 5000)
            logger.info(f"[NumericAudit] Sampled 5000 of {_orig_n} allowed values")

        logger.debug(f"[NumericAudit] extracted {len(allowed)} allowed numbers")
        return allowed

    def _scrape_numbers(
        self,
        obj: Any,
        source_id: str,
        label: str,
        allowed: AllowedNumberSet,
        max_depth: int = 6,
    ) -> None:
        """Recursively walk dict/list/str and extract all numeric values."""
        if max_depth <= 0:
            return
        if isinstance(obj, bool):
            return  # avoid treating True/False as 1/0
        if isinstance(obj, (int, float)):
            allowed.add(float(obj), source_id, label)
            return
        if isinstance(obj, str):
            # Extract numbers from string fields too — many tool results
            # serialize values as "65%" or "1.38 mm/s"
            for m in _NUMERIC_RE.finditer(obj):
                val = _parse_number(m.group(1))
                if val is not None:
                    allowed.add(val, source_id, f"{label}:str")
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                self._scrape_numbers(v, source_id, f"{label}:{k}", allowed, max_depth - 1)
            return
        if isinstance(obj, (list, tuple)):
            for item in obj[:200]:  # cap to prevent runaway
                self._scrape_numbers(item, source_id, label, allowed, max_depth - 1)
            return

    # ── audit advisory output ──────────────────────────────────────────

    def audit_advisory_json(
        self,
        advisory_text: str,
        allowed: AllowedNumberSet,
    ) -> AuditReport:
        """
        Scan synthesis output for numeric tokens. Each gets matched against
        the allowed set with tolerance. Whitelist patterns (dates, equipment
        IDs, ULIDs, cluster references) bypass.
        """
        report = AuditReport()
        if not advisory_text:
            return report

        # Try JSON parse; if it fails treat the whole string as one text blob
        text_chunks: List[Tuple[str, str]] = []  # (field_name, text)
        try:
            data = json.loads(advisory_text)
            if isinstance(data, dict):
                # Pull just the human-readable narrative fields. Skip frontmatter
                # numerics that aren't claims (confidence, evidence_ids etc).
                if "analysis" in data:
                    text_chunks.append(("analysis", str(data["analysis"])))
                for i, adv in enumerate(data.get("advisories", []) or []):
                    if not isinstance(adv, dict):
                        continue
                    if adv.get("message"):
                        text_chunks.append((f"advisory[{i}].message", str(adv["message"])))
                    if adv.get("recommended_action"):
                        text_chunks.append((f"advisory[{i}].recommended_action", json.dumps(adv["recommended_action"])))
                    # impact field — usually computed numbers, audit these explicitly
                    imp = adv.get("impact") or {}
                    if isinstance(imp, dict):
                        for k, v in imp.items():
                            if isinstance(v, (int, float)):
                                text_chunks.append((f"advisory[{i}].impact.{k}", str(v)))
            else:
                text_chunks.append(("body", advisory_text))
        except json.JSONDecodeError:
            text_chunks.append(("body", advisory_text))

        allowed_vals = allowed.values()

        for field_name, text in text_chunks:
            for m in _NUMERIC_RE.finditer(text):
                token = m.group(1)
                val = _parse_number(token)
                if val is None:
                    continue
                report.total_numbers += 1

                # Whitelist context check (dates / equipment IDs / cluster refs)
                if _is_whitelisted_context(text, m.start(), m.end()):
                    continue

                # Tiny integers (≤ 10) are almost always counts / IDs — skip
                if val == int(val) and abs(val) <= 10:
                    continue

                # Try match
                matched = None
                for aval in allowed_vals:
                    if _numbers_match(val, aval):
                        matched = next((a for a in allowed.items if a.value == aval), None)
                        break

                nmatch = NumericMatch(
                    output_value=val,
                    matched_to=matched,
                    surface_form=token,
                    span=(m.start(), m.end()),
                    context_field=field_name,
                )
                if matched is not None:
                    report.matched.append(nmatch)
                else:
                    report.orphans.append(nmatch)

        return report

    # ── strip orphan numbers from advisory ─────────────────────────────

    def strip_orphans(self, advisory_text: str, report: AuditReport) -> str:
        """
        Replace orphan numeric tokens in advisory message fields with
        `[unverified]` placeholder. Returns sanitized JSON string.

        If parsing fails, applies replacement to the raw string as best-effort.
        """
        if not report.orphans:
            return advisory_text

        orphan_tokens = {m.surface_form for m in report.orphans}

        def _strip_text(s: str) -> str:
            out = s
            for token in orphan_tokens:
                # Replace each orphan token with [unverified]. Use \b-style
                # boundary to avoid matching mid-equipment-ID.
                out = re.sub(
                    rf"(?<![A-Za-z_]){re.escape(token)}(?![A-Za-z_])",
                    "[unverified]",
                    out,
                )
            return out

        try:
            data = json.loads(advisory_text)
            if isinstance(data, dict):
                if "analysis" in data and isinstance(data["analysis"], str):
                    data["analysis"] = _strip_text(data["analysis"])
                for adv in data.get("advisories", []) or []:
                    if not isinstance(adv, dict):
                        continue
                    if isinstance(adv.get("message"), str):
                        adv["message"] = _strip_text(adv["message"])
                    ra = adv.get("recommended_action")
                    if isinstance(ra, dict):
                        for k, v in list(ra.items()):
                            if isinstance(v, str):
                                ra[k] = _strip_text(v)
                    # Strip orphan numerics from impact too (replace with 0 + flag)
                    imp = adv.get("impact")
                    if isinstance(imp, dict):
                        for k, v in list(imp.items()):
                            if isinstance(v, (int, float)) and str(v) in orphan_tokens:
                                imp[k] = 0.0
                                imp[f"{k}_unverified"] = True
                return json.dumps(data)
        except json.JSONDecodeError:
            pass

    def prune_for_synthesis(
        self,
        allowed: AllowedNumberSet,
        query: str,
        cap: int = 500
    ) -> AllowedNumberSet:
        """
        Prune allowed numbers based on relevance to query and recency.
        """
        if not allowed.items:
            return allowed

        # Extract equipment IDs from the query
        eq_re = re.compile(r"\b(?:CH|AHU|VAV|FCU|CT|CHWP|CDWP|ZONE|FLOOR|METER|PCHWP|SCHWP)-\d+[A-Z]?\b", re.IGNORECASE)
        query_eqs = set(eq_re.findall(query.upper()))

        scored_items = []
        for a in allowed.items:
            score = 0.0
            label_upper = a.label.upper()
            source_upper = a.source_id.upper()

            # Boost if related to query equipment
            for eq in query_eqs:
                if eq in label_upper or eq in source_upper:
                    score += 1000.0

            # Boost if related to active alarms
            if "ALARM" in label_upper or "ALARM" in source_upper:
                score += 100.0

            # Boost recent / live snapshot
            if "SNAPSHOT" in label_upper or "SNAPSHOT" in source_upper:
                score += 10.0

            scored_items.append((score, a))

        # Sort descending by score
        scored_items.sort(key=lambda x: x[0], reverse=True)

        pruned = AllowedNumberSet()
        for _, a in scored_items[:cap]:
            pruned.items.append(a)

        return pruned

    # ── prompt-injection helper ────────────────────────────────────────

    @staticmethod
    def build_allowed_numbers_prompt(allowed: AllowedNumberSet, cap: int = 200) -> str:
        """
        Build a compact prompt block listing the allowed numbers + sources
        for the synthesis LLM to see. Caps at `cap` distinct values to keep
        prompt size bounded.
        """
        if not allowed.items:
            return ""
        # Deduplicate by (rounded value, source_id) to keep block compact
        seen: Set[Tuple[float, str]] = set()
        rows: List[str] = []
        for a in allowed.items:
            key = (round(a.value, 4), a.source_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append(f"  - {a.value:g}  (source: {a.source_id[:30]} | {a.label[:50]})")
            if len(rows) >= cap:
                break
        return (
            "\n\n--- ALLOWED NUMERIC VALUES (deterministic extract from evidence) ---\n"
            "Every numeric value you cite in your advisory MUST appear in this list "
            "within 2% tolerance. Numbers outside this list will be DETERMINISTICALLY "
            "STRIPPED post-synthesis and replaced with [unverified]. Cite exact values.\n"
            + "\n".join(rows)
            + "\n--- END ALLOWED NUMERIC VALUES ---\n"
        )

    def strip_mismatched_assertions(self, advisory_text: str, context: Optional[Dict[str, Any]]) -> str:
        """
        Scan advisory text for categorical claims like "short-cycling" or "compressor surge"
        and strip or neutralize them if the actual telemetry facts table shows 0.0 or is absent for that category.
        """
        if not advisory_text or not context:
            return advisory_text
            
        # 1. Build facts from snapshot
        facts = {}
        try:
            snap = context.get("LIVE_BMS_SNAPSHOT")
            if isinstance(snap, dict):
                for eq_block in snap.get("equipment_status", []):
                    eq_id = eq_block.get("id")
                    if eq_id:
                        pts = eq_block.get("points", {})
                        sc_val = 0.0
                        surge_val = 0.0
                        for pk, pv in pts.items():
                            pk_lower = pk.lower()
                            val = pv.get("value") if isinstance(pv, dict) else pv
                            try:
                                if "short_cycling" in pk_lower or "short cycling" in pk_lower:
                                    sc_val = float(val)
                                if "surge" in pk_lower:
                                    surge_val = float(val)
                            except (TypeError, ValueError):
                                pass
                        facts[eq_id] = {
                            "short_cycling": sc_val,
                            "surge": surge_val
                        }
        except Exception:
            return advisory_text
            
        if not facts:
            return advisory_text
            
        def _sanitize(text: str) -> str:
            if not isinstance(text, str):
                return text
            # We split the text into sentences
            sentences = re.split(r'(?<=[.!?])\s+', text)
            filtered_sentences = []
            for sentence in sentences:
                sentence_upper = sentence.upper()
                keep = True
                
                # Check for short-cycling assertions
                if "SHORT-CYCLING" in sentence_upper or "SHORT CYCLING" in sentence_upper:
                    # Find which equipment is mentioned
                    for eq_id, eq_facts in facts.items():
                        if eq_id.upper() in sentence_upper:
                            if eq_facts.get("short_cycling", 0.0) == 0.0:
                                # Telemetry says NO short-cycling, but sentence claims it! Strip/neutralize.
                                logger.warning(f"[NumericAudit] Stripping short-cycling assertion for {eq_id} (telemetry shows 0.0)")
                                keep = False
                                break
                                
                # Check for surge assertions
                if "SURGE" in sentence_upper:
                    for eq_id, eq_facts in facts.items():
                        if eq_id.upper() in sentence_upper:
                            if eq_facts.get("surge", 0.0) == 0.0:
                                logger.warning(f"[NumericAudit] Stripping surge assertion for {eq_id} (telemetry shows 0.0)")
                                keep = False
                                break
                                
                if keep:
                    filtered_sentences.append(sentence)
            return " ".join(filtered_sentences)
            
        try:
            data = json.loads(advisory_text)
            if isinstance(data, dict):
                if "analysis" in data and isinstance(data["analysis"], str):
                    data["analysis"] = _sanitize(data["analysis"])
                for adv in data.get("advisories", []) or []:
                    if not isinstance(adv, dict):
                        continue
                    if isinstance(adv.get("message"), str):
                        adv["message"] = _sanitize(adv["message"])
                    ra = adv.get("recommended_action")
                    if isinstance(ra, dict):
                        for k, v in list(ra.items()):
                            if isinstance(v, str):
                                ra[k] = _sanitize(v)
                return json.dumps(data)
        except Exception:
            pass
            
        return _sanitize(advisory_text)

