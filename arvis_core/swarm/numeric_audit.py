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
class QuantifiedClaim:
    claim_id: str
    value: float
    unit: str
    confidence: float
    is_directly_measured: bool
    derivation_method: str
    evidence_ids: List[str]
    uncertainty_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "value": self.value,
            "unit": self.unit,
            "confidence": self.confidence,
            "is_directly_measured": self.is_directly_measured,
            "derivation_method": self.derivation_method,
            "evidence_ids": self.evidence_ids,
            "uncertainty_reason": self.uncertainty_reason
        }


@dataclass
class NumericMatch:
    output_value: float
    matched_to: Optional[AllowedNumber]
    surface_form: str          # original token as it appeared in the advisory
    span: Tuple[int, int]      # (start, end) in scanned text
    context_field: str         # "message" | "analysis" | "impact"
    claim_id: Optional[str] = None


def _is_derived_allowed_number(a: AllowedNumber) -> bool:
    """Check if an AllowedNumber is derived rather than direct telemetry."""
    src = a.source_id.lower()
    lbl = a.label.lower()
    if src.startswith("derived:") or "pct" in lbl or "fraction" in lbl or "complement" in lbl or "leak" in lbl or "delta" in lbl:
        return True
    return False


def get_confidence_and_provenance(allowed_num: AllowedNumber) -> Tuple[float, bool, str, List[str], str]:
    """
    Returns (confidence, is_directly_measured, derivation_method, evidence_ids, uncertainty_reason)
    based on the allowed number's derivation basis.
    """
    src = allowed_num.source_id.lower()
    lbl = allowed_num.label.lower()
    
    # Extract evidence IDs from source_id packed using pipe format
    evidence_ids = []
    if "|" in allowed_num.source_id:
        _, ev_str = allowed_num.source_id.split("|", 1)
        evidence_ids = [eid.strip() for eid in ev_str.split(",") if eid.strip()]
    else:
        if allowed_num.source_id and allowed_num.source_id != "snapshot" and not allowed_num.source_id.startswith("derived:"):
            evidence_ids = [allowed_num.source_id]
            
    # Remove any potential duplicate "derived" prefixes or other subfields from raw evidence IDs
    evidence_ids = [eid for eid in evidence_ids if not eid.startswith("derived:")]

    if "oa_frac" in lbl or "oa_pct" in lbl or "oa_leak" in lbl or "derived:oa_" in src:
        return (0.65, False, "physics_mixing_equation", evidence_ids, "Inferred from Mixed-Air/Outdoor-Air/Return-Air temperature mixing equation")
    elif "temp_delta" in src or "delta(" in lbl:
        return (0.80, False, "temperature_delta", evidence_ids, "Calculated difference between two measured temperature points")
    elif "complement" in lbl or "pct_leak" in lbl:
        return (0.85, False, "complement_calculation", evidence_ids, "Calculated complement (100 - x) of a measured or derived value")
    elif "fraction" in lbl or "pct" in lbl:
        return (0.90, False, "unit_conversion", evidence_ids, "Converted between fraction and percentage representation")
    elif src.startswith("derived:"):
        return (0.50, False, "multi_step_inference", evidence_ids, "Derived through multi-step building logic inference")
    else:
        return (0.95, True, "direct_telemetry", evidence_ids, "Directly measured by BMS sensor")


@dataclass
class AuditReport:
    total_numbers: int = 0
    matched: List[NumericMatch] = field(default_factory=list)
    orphans: List[NumericMatch] = field(default_factory=list)
    derived_claims: List[QuantifiedClaim] = field(default_factory=list)

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

        # First-principles thermodynamic derivations
        try:
            # 1. Identify all temperature items in `allowed`
            temp_items = [a for a in allowed.items if 10.0 <= a.value <= 55.0]
            if len(temp_items) >= 2:
                # Add differences (temperature deltas)
                for i in range(len(temp_items)):
                    for j in range(i + 1, len(temp_items)):
                        t1_item, t2_item = temp_items[i], temp_items[j]
                        t1, t2 = t1_item.value, t2_item.value
                        delta = abs(t1 - t2)
                        ev_ids = sorted(list(set([t1_item.source_id, t2_item.source_id])))
                        ev_str = ",".join(ev_ids)
                        allowed.add(delta, f"derived:temp_delta|{ev_str}", f"delta({t1:.1f}-{t2:.1f})")
                        
            # 2. Mixed-air OA fraction / damper percentage calculation
            # Form: (T_mat - T_rat) / (T_oat - T_rat)
            oat_items = [a for a in allowed.items if "oat" in a.label.lower() or "outdoor" in a.label.lower()]
            rat_items = [a for a in allowed.items if "rat" in a.label.lower() or "return" in a.label.lower()]
            mat_items = [a for a in allowed.items if "mat" in a.label.lower() or "mixed" in a.label.lower()]
            
            # If explicit keys are absent, fallback to any plausible T_oat, T_rat, T_mat items
            if not oat_items:
                oat_items = [a for a in temp_items if a.value >= 30.0]  # outdoor air in Qatar is hot
            if not rat_items:
                rat_items = [a for a in temp_items if 21.0 <= a.value <= 25.0]  # return air is room temperature
            if not mat_items:
                mat_items = [a for a in temp_items if 24.0 <= a.value <= 32.0]  # mixed air is in between
                
            for oat_item in oat_items:
                for rat_item in rat_items:
                    for mat_item in mat_items:
                        oat, rat, mat = oat_item.value, rat_item.value, mat_item.value
                        if abs(oat - rat) > 1.0:
                            oa_frac = (mat - rat) / (oat - rat)
                            if 0.0 <= oa_frac <= 1.0:
                                ev_ids = sorted(list(set([oat_item.source_id, rat_item.source_id, mat_item.source_id])))
                                ev_str = ",".join(ev_ids)
                                allowed.add(oa_frac, f"derived:oa_fraction|{ev_str}", f"oa_frac({mat}/{oat}/{rat})")
                                allowed.add(oa_frac * 100.0, f"derived:oa_pct|{ev_str}", f"oa_pct({mat}/{oat}/{rat})")
                                # Counterfactual (e.g. bypass, leakage)
                                allowed.add(100.0 - (oa_frac * 100.0), f"derived:oa_leak_pct|{ev_str}", f"oa_leak_pct({mat}/{oat}/{rat})")

            # 3. Add general scale/conversions (fractions to percentages and vice-versa)
            extra_vals = []
            for a in allowed.items:
                v = a.value
                # If it's a fraction 0-1, add percentage
                if 0.0 < v <= 1.0:
                    extra_vals.append((v * 100.0, f"{a.source_id}", f"{a.label}:pct"))
                    extra_vals.append((100.0 - (v * 100.0), f"{a.source_id}", f"{a.label}:pct_leak"))
                # If it's a percentage 0-100, add fraction
                elif 1.0 < v <= 100.0:
                    extra_vals.append((v / 100.0, f"{a.source_id}", f"{a.label}:fraction"))
                    extra_vals.append((100.0 - v, f"{a.source_id}", f"{a.label}:complement"))
                    
            for val, src, lbl in extra_vals:
                allowed.add(val, src, lbl)
                
        except Exception as _deriv_err:
            logger.debug(f"[NumericAudit] derived number generation failed: {_deriv_err}")

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

                claim_id = None
                if matched is not None and _is_derived_allowed_number(matched):
                    confidence, is_directly_measured, derivation_method, evidence_ids, uncertainty_reason = get_confidence_and_provenance(matched)
                    claim_id = f"claim_est_{len(report.derived_claims) + 1}"
                    # Infer unit
                    unit = "percent"
                    lbl_lower = matched.label.lower()
                    if "celsius" in lbl_lower or "delta" in lbl_lower or "temp" in lbl_lower or " C" in matched.label or "°C" in matched.label:
                        unit = "celsius"
                    elif "fraction" in lbl_lower:
                        unit = "fraction"
                    
                    claim = QuantifiedClaim(
                        claim_id=claim_id,
                        value=matched.value,
                        unit=unit,
                        confidence=confidence,
                        is_directly_measured=is_directly_measured,
                        derivation_method=derivation_method,
                        evidence_ids=evidence_ids,
                        uncertainty_reason=uncertainty_reason
                    )
                    report.derived_claims.append(claim)

                nmatch = NumericMatch(
                    output_value=val,
                    matched_to=matched,
                    surface_form=token,
                    span=(m.start(), m.end()),
                    context_field=field_name,
                    claim_id=claim_id,
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
        `[unverified]` placeholder, and replace derived claims with their
        respective `{claim_id}` placeholders. Returns sanitized JSON string.

        If parsing fails, applies replacement to the raw string as best-effort.
        """
        if not report.orphans and not report.derived_claims:
            return advisory_text

        # Only strip true orphans. Derived/matched claims already correspond to an
        # allowed (grounded) value, so leaving the real number inline is correct.
        # Replacing them with {claim_est_N} placeholders requires a downstream
        # substitution renderer that does not run before final output — doing so
        # leaks literal "{claim_est_13}" tokens into the advisory prose. Keep the
        # computed_claims provenance block, but never mutate the inline numbers.
        all_matches: List[NumericMatch] = []
        for m in report.orphans:
            all_matches.append(m)

        from collections import defaultdict
        matches_by_field = defaultdict(list)
        for m in all_matches:
            matches_by_field[m.context_field].append(m)

        def _replace_spans(text: str, matches: List[NumericMatch]) -> str:
            # Sort matches in descending order of span start index so replacements don't shift earlier indices
            sorted_matches = sorted(matches, key=lambda x: x.span[0], reverse=True)
            chars = list(text)
            for m in sorted_matches:
                start, end = m.span
                # Ensure the span is valid and matches the token
                if start >= 0 and end <= len(chars) and "".join(chars[start:end]) == m.surface_form:
                    replacement = f"{{{m.claim_id}}}" if m.claim_id else "[unverified]"
                    chars[start:end] = list(replacement)
            return "".join(chars)

        try:
            data = json.loads(advisory_text)
            if isinstance(data, dict):
                # Inject computed_claims top-level block
                if report.derived_claims:
                    data["computed_claims"] = [c.to_dict() for c in report.derived_claims]

                # Perform field-by-field replacements
                if "analysis" in data and isinstance(data["analysis"], str):
                    field_matches = matches_by_field.get("analysis", [])
                    if field_matches:
                        data["analysis"] = _replace_spans(data["analysis"], field_matches)

                for i, adv in enumerate(data.get("advisories", []) or []):
                    if not isinstance(adv, dict):
                        continue

                    msg_field = f"advisory[{i}].message"
                    if msg_field in matches_by_field and isinstance(adv.get("message"), str):
                        adv["message"] = _replace_spans(adv["message"], matches_by_field[msg_field])

                    ra = adv.get("recommended_action")
                    if isinstance(ra, dict):
                        ra_field = f"advisory[{i}].recommended_action"
                        if ra_field in matches_by_field:
                            ra_str = json.dumps(ra)
                            ra_str_replaced = _replace_spans(ra_str, matches_by_field[ra_field])
                            try:
                                adv["recommended_action"] = json.loads(ra_str_replaced)
                            except Exception:
                                pass

                    imp = adv.get("impact")
                    if isinstance(imp, dict):
                        for k, v in list(imp.items()):
                            imp_field = f"advisory[{i}].impact.{k}"
                            if imp_field in matches_by_field:
                                m = matches_by_field[imp_field][0]
                                if m.claim_id:
                                    imp[k] = m.output_value
                                    imp[f"{k}_claim_id"] = m.claim_id
                                else:
                                    imp[k] = 0.0
                                    imp[f"{k}_unverified"] = True
                return json.dumps(data)
        except json.JSONDecodeError:
            pass

        # Fallback to raw string replacement
        body_matches = matches_by_field.get("body", [])
        if body_matches:
            return _replace_spans(advisory_text, body_matches)
        return advisory_text

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

