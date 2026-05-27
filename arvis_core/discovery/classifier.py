"""Criticality + cadence classifier — HYBRID.

Phase 1 (current): rule-based, name-pattern matching. Every decision is
logged to SQLite with its feature vector so a LightGBM model can be trained
once operator feedback labels accumulate.

Phase 2 (future): ML model trained nightly. Loads here if `ml_model` is set;
consulted alongside rules. Rules remain the safety floor until ML confidence
on a held-out set exceeds 0.7.

DO NOT REMOVE the rule-based path until ML AUC > 0.85 + holdout-recall on the
CRITICAL class > 0.95. The bootstrap classifier is the safety net.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("arvis.discovery.classifier")


class PointCriticality(Enum):
    CRITICAL = "critical"
    NICE_TO_HAVE = "nice_to_have"
    COSMETIC = "cosmetic"
    UNKNOWN = "unknown"


@dataclass
class ClassificationResult:
    criticality: PointCriticality
    cadence_seconds: float
    confidence: float
    method: str  # "rules" | "ml" | "hybrid"
    feature_vector: dict = field(default_factory=dict)
    reasoning: str = ""


# --- Rule classifier (PHASE_1_BOOTSTRAP — replaced by ML in Phase 2) -------

# PHASE_1_BOOTSTRAP — replaced by ML in Phase 2
_CRITICAL_NAME_PATTERNS = {
    "CWS", "CWR", "CHWST", "CHWRT",
    "FLT_DP", "FILTER_DP",
    "SUC_PRES", "DIS_PRES", "OIL_PRES_DIFF",
    "VIB_RMS", "VIB_PEAK",
    "MOTOR_WINDING_TEMP", "BEARING_TEMP",
    "STATUS", "FAULT", "ALARM",
    "SAT", "MAT", "RAT",
}

# PHASE_1_BOOTSTRAP — replaced by ML in Phase 2
_NICE_NAME_PATTERNS = {
    "KW", "AMP", "VFD_SPD", "FAN_SPD", "PUMP_SPD",
    "CHW_VALVE", "OA_DMPR", "RA_DMPR", "EA_DMPR",
    "ZONE_TEMP", "SETPOINT",
}

# PHASE_1_BOOTSTRAP — replaced by ML in Phase 2
_COSMETIC_NAME_PATTERNS = {"RUNTIME_HRS", "STARTS", "DESCRIPTION", "TAG"}

# PHASE_1_BOOTSTRAP — replaced by ML in Phase 2
_CADENCE_RULES = {
    "vibration": 1.0,        # 1s
    "pressure": 5.0,         # 5s
    "temperature": 60.0,     # 60s
    "status": 5.0,           # 5s
    "valve_position": 30.0,
    "counter": 300.0,        # 5 min
    "default": 60.0,
}


def _infer_point_type(point_name: str) -> str:
    # PHASE_1_BOOTSTRAP — replaced by ML in Phase 2
    n = point_name.upper()
    if "VIB" in n:
        return "vibration"
    if "PRES" in n:
        return "pressure"
    if "TEMP" in n or n.endswith("_T"):
        return "temperature"
    if "STATUS" in n or "FAULT" in n:
        return "status"
    if "VALVE" in n or "DMPR" in n:
        return "valve_position"
    if "RUNTIME" in n or "STARTS" in n:
        return "counter"
    return "default"


class HybridClassifier:
    """Phase 1: rules. Phase 2: ML model loads here when trained."""

    def __init__(self, training_db_path: str) -> None:
        self.training_db = Path(training_db_path)
        self.training_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.training_db)) as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS classification_labels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    point_id TEXT NOT NULL,
                    point_name TEXT,
                    equipment_type TEXT,
                    bacnet_object_type TEXT,
                    features_json TEXT,
                    rule_prediction TEXT,
                    ml_prediction TEXT,
                    final_label TEXT,
                    source TEXT,
                    outcome TEXT
                )"""
            )
        self._ml_model = None  # Phase 2: trained LightGBM loads here
        self._ml_confidence_threshold = 0.7

    # ------------------------------------------------------------------ public
    def classify(self, point_meta) -> ClassificationResult:
        """Hybrid classify: rules primary, ML consulted if loaded + confident."""
        features = self._extract_features(point_meta)
        rule_result = self._classify_by_rules(point_meta, features)

        if self._ml_model is not None:
            try:
                ml_result = self._classify_by_ml(features)
            except NotImplementedError:
                ml_result = None
            if ml_result is not None:
                if ml_result.confidence >= self._ml_confidence_threshold:
                    self._log_label(
                        point_meta, features, rule_result, ml_result,
                        ml_result.criticality.value, "ml",
                    )
                    return ml_result
                # Disagreement → ensemble vote, safety-bias to CRITICAL
                if (
                    ml_result.criticality == PointCriticality.CRITICAL
                    or rule_result.criticality == PointCriticality.CRITICAL
                ):
                    rule_result.criticality = PointCriticality.CRITICAL
                    rule_result.method = "hybrid_safety_bias"

        self._log_label(
            point_meta, features, rule_result, None,
            rule_result.criticality.value, "rules",
        )
        return rule_result

    def record_feedback(self, point_id: str, operator_label: str, was_useful: bool) -> None:
        """Operator feedback — the primary ML training signal.

        Updates the most recent pending label row for `point_id`.
        """
        with sqlite3.connect(str(self.training_db)) as c:
            c.execute(
                """UPDATE classification_labels
                   SET final_label = ?, outcome = ?
                   WHERE id = (
                     SELECT id FROM classification_labels
                     WHERE point_id = ? AND outcome = 'pending'
                     ORDER BY ts DESC LIMIT 1
                   )""",
                (operator_label, "useful" if was_useful else "rejected", point_id),
            )

    # --------------------------------------------------------------- internals
    def _classify_by_rules(self, point_meta, features: dict) -> ClassificationResult:
        # PHASE_1_BOOTSTRAP — replaced by ML in Phase 2
        name = (getattr(point_meta, "point_name", "") or "").upper()

        crit_match = next((p for p in _CRITICAL_NAME_PATTERNS if p in name), None)
        if crit_match:
            ptype = _infer_point_type(name)
            return ClassificationResult(
                criticality=PointCriticality.CRITICAL,
                cadence_seconds=_CADENCE_RULES.get(ptype, 60.0),
                confidence=0.85,
                method="rules",
                feature_vector=features,
                reasoning=f"name matches critical pattern '{crit_match}'",
            )

        nice_match = next((p for p in _NICE_NAME_PATTERNS if p in name), None)
        if nice_match:
            ptype = _infer_point_type(name)
            return ClassificationResult(
                criticality=PointCriticality.NICE_TO_HAVE,
                cadence_seconds=_CADENCE_RULES.get(ptype, 60.0),
                confidence=0.7,
                method="rules",
                feature_vector=features,
                reasoning=f"name matches nice-to-have pattern '{nice_match}'",
            )

        cos_match = next((p for p in _COSMETIC_NAME_PATTERNS if p in name), None)
        if cos_match:
            return ClassificationResult(
                criticality=PointCriticality.COSMETIC,
                cadence_seconds=300.0,
                confidence=0.6,
                method="rules",
                feature_vector=features,
                reasoning=f"name matches cosmetic pattern '{cos_match}'",
            )

        return ClassificationResult(
            criticality=PointCriticality.UNKNOWN,
            cadence_seconds=60.0,
            confidence=0.3,
            method="rules",
            feature_vector=features,
            reasoning="no pattern match — defer to operator approval",
        )

    def _classify_by_ml(self, features: dict) -> ClassificationResult:
        # Phase 2 placeholder — LightGBM .predict_proba goes here.
        raise NotImplementedError("ML model not loaded — Phase 2")

    def _extract_features(self, point_meta) -> dict:
        name = (getattr(point_meta, "point_name", "") or "").upper()
        device_id = getattr(point_meta, "device_id", "") or ""
        return {
            "name_length": len(name),
            "has_pres": int("PRES" in name),
            "has_temp": int("TEMP" in name),
            "has_vib": int("VIB" in name),
            "has_status": int("STATUS" in name),
            "has_dp": int("DP" in name),
            "object_type": getattr(point_meta, "bacnet_object_type", None) or "unknown",
            "has_unit": int(bool(getattr(point_meta, "unit", None))),
            "equipment_type": device_id.split("-")[0] if device_id else "",
        }

    def _log_label(
        self,
        point_meta,
        features: dict,
        rule_result: ClassificationResult,
        ml_result: Optional[ClassificationResult],
        final_label: str,
        source: str,
    ) -> None:
        try:
            with sqlite3.connect(str(self.training_db)) as c:
                c.execute(
                    """INSERT INTO classification_labels
                       (ts, point_id, point_name, equipment_type, bacnet_object_type,
                        features_json, rule_prediction, ml_prediction, final_label,
                        source, outcome)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        time.time(),
                        getattr(point_meta, "point_id", None),
                        getattr(point_meta, "point_name", None),
                        features.get("equipment_type"),
                        getattr(point_meta, "bacnet_object_type", None),
                        json.dumps(features, default=str),
                        rule_result.criticality.value,
                        ml_result.criticality.value if ml_result else None,
                        final_label,
                        source,
                        "pending",
                    ),
                )
        except Exception as e:
            logger.debug("[Classifier] label log skipped: %s", e)


def maybe_retrain_ml_model(training_db_path: str, min_labels: int = 100) -> bool:
    """Nightly retraining job — placeholder.

    Reads labeled rows from `classification_labels` (outcome IN useful/rejected),
    and once we have `min_labels` examples, trains a LightGBM classifier on the
    feature_vector → final_label mapping. For now this is a stub that simply
    reports whether we have enough labels.

    Returns True if a model was actually trained.
    """
    db = Path(training_db_path)
    if not db.exists():
        return False
    with sqlite3.connect(str(db)) as c:
        c.row_factory = sqlite3.Row
        labels = c.execute(
            "SELECT COUNT(*) AS n FROM classification_labels "
            "WHERE outcome IN ('useful','rejected')"
        ).fetchone()
    if not labels or labels["n"] < min_labels:
        logger.info(
            "[Discovery] Retrain skipped: %d labels (need %d)",
            labels["n"] if labels else 0,
            min_labels,
        )
        return False
    # Phase 2: import lightgbm, build feature matrix, fit, persist to disk,
    # then have HybridClassifier hot-reload via a separate API.
    logger.info("[Discovery] Retrain placeholder hit with %d labels — Phase 2 TODO", labels["n"])
    return False
