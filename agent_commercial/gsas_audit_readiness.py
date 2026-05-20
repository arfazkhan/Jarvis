import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class GSASAuditReadinessChecker:
    """
    Evaluates whether the building is continuously ready for a GSAS audit.
    Checks for minimum evidence, survey responses, waste records, and blocking issues.
    """
    
    def __init__(self, gsas_reporter: Any, survey_manager: Any = None):
        self.reporter = gsas_reporter
        self.survey_manager = survey_manager
        
    def check_readiness(self) -> Dict[str, Any]:
        """
        Runs a full audit readiness check and returns the results.
        """
        logger.info("Running GSAS Audit Readiness Check")
        
        blocking_issues = []
        warnings = []
        
        # 1. Check GSAS Score Status
        if not hasattr(self.reporter, 'criteria') or not self.reporter.criteria:
            blocking_issues.append("GSAS Criteria are not initialized or evaluated.")
            return self._build_report(0, blocking_issues, warnings)
            
        score = self.reporter.calculate_overall_score()
        if score < 1.0:  # 1.0 minimum threshold on 0-3.0 scale (equivalent to 1-star)
            blocking_issues.append(f"Overall GSAS score is too low for certification ({score:.2f}/3.0). Minimum required is 1.0.")
            
        # 2. Category Level Guardrails (e.g. Energy and Water disqualifications)
        cat_scores = self.reporter.calculate_category_scores()
        e_cat = cat_scores.get("E")
        w_cat = cat_scores.get("W")
        
        if e_cat and e_cat.max_points > 0 and (e_cat.achieved_points / e_cat.max_points) < 0.20:
            blocking_issues.append("Energy category score is below the 20% disqualification threshold.")
        if w_cat and w_cat.max_points > 0 and (w_cat.achieved_points / w_cat.max_points) < 0.20:
            blocking_issues.append("Water category score is below the 20% disqualification threshold.")

        # 3. Survey Responses (for IE category)
        if self.survey_manager:
            survey_data = self.survey_manager.get_gsas_ie_data()
            if survey_data.get("response_count", 0) < 50:
                warnings.append(f"Low survey response count ({survey_data.get('response_count', 0)}). Minimum 50 recommended for IE compliance.")
        else:
            warnings.append("Survey Manager is offline. Cannot verify IE survey compliance.")
            
        # 4. Data Completeness & Evidence
        # In a real system, we'd check if utility bills and waste logs exist for the trailing 12 months
        # Mocking the check based on standard BMS properties
        metrics = getattr(self.reporter, 'bms_state', None)
        if not metrics:
            warnings.append("BMS state is not connected to reporter. Cannot verify data completeness.")
            
        # Calculate Readiness Score
        # Readiness score is informational only. Use is_audit_ready for pass/fail.
        # 100 = fully ready, decremented by blocking issues (20pts each) and warnings (5pts each)
        readiness_score = 100.0
        readiness_score -= len(blocking_issues) * 20.0
        readiness_score -= len(warnings) * 5.0
        
        # If there are blocking issues, the readiness score shouldn't be higher than 50
        if blocking_issues:
            readiness_score = min(readiness_score, 50.0)
            
        readiness_score = max(0.0, readiness_score)
        
        return self._build_report(readiness_score, blocking_issues, warnings)

    def _build_report(self, score: float, blocks: List[str], warnings: List[str]) -> Dict[str, Any]:
        return {
            "audit_readiness_score": round(score, 1),
            "is_audit_ready": len(blocks) == 0,
            "blocking_issues": blocks,
            "warnings": warnings
        }
