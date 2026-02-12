"""
Response Modes for ARVIS RAG
=============================

Confidence-aware response system that never invents, never stays silent,
and always moves the technician forward.

MODES:
- A: Documented Procedure (step-by-step from manual)
- B: Parameters + Guidance (known limits, operational hints)  
- C: Cross-Document Hint (point to other manuals)
- D: Escalation (safety-critical, structured refusal)
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import re


class ResponseMode(Enum):
    """The four response modes ARVIS can use."""
    MODE_A = "documented_procedure"   # Best case: step-by-step
    MODE_B = "parameters_guidance"    # Known limits + operational hints
    MODE_C = "cross_document_hint"    # Point to other manuals
    MODE_D = "escalation"             # Safety-critical, can't help


class RiskLevel(Enum):
    """Risk classification for procedural questions."""
    HIGH = "high"       # Never improvise (refrigerant, electrical, lockout)
    MEDIUM = "medium"   # Caution (troubleshoot, diagnose)
    LOW = "low"         # Usually answerable (settings, navigation)


class QuestionType(Enum):
    """Classification of question types - distinguishes SAFE extractive from DANGEROUS procedural."""
    # SAFE: Table-driven, can summarize
    EXTRACTIVE = "extractive"             # "What is..." - summarize from tables
    DIAGNOSTIC = "diagnostic"             # "How do I check..." - often answerable from specs
    NAVIGATION = "navigation"             # "How do I access..." - UI/settings
    
    # DANGEROUS: Never improvise
    MECHANICAL_PROCEDURE = "mechanical"   # "How do I charge..." - physical work
    SAFETY_PROCEDURE = "safety"           # Anything with lockout/tagout implications


class AnswerStrategy(Enum):
    """How ARVIS should approach the answer."""
    SUMMARIZE = "summarize"          # Aggregate data from tables, provide ranges
    EXTRACT = "extract"              # Pull specific values
    GUIDE = "guide"                  # Provide orientation without steps
    REFUSE = "refuse"                # Too dangerous, escalate


# ============================================================================
# RISK CLASSIFICATION
# ============================================================================

HIGH_RISK_KEYWORDS = [
    "refrigerant", "charge", "recharge", "vacuum", "recover",
    "electrical", "voltage", "lockout", "tagout", "loto",
    "pressure", "high pressure", "low pressure", "relief",
    "safety", "interlock", "emergency", "shutdown",
    "wiring", "disconnect", "breaker", "capacitor",
    "oil", "lubrication", "bearing",
]

MEDIUM_RISK_KEYWORDS = [
    "troubleshoot", "diagnose", "fault", "error", "alarm",
    "repair", "replace", "fix", "service", "maintenance",
    "compressor", "motor", "pump", "fan",
    "leak", "noise", "vibration",
]

LOW_RISK_KEYWORDS = [
    "settings", "configuration", "parameter", "setpoint",
    "display", "screen", "menu", "navigation", "access",
    "schedule", "timer", "zone", "mode",
    "reading", "value", "status", "check",
]

MANUAL_TYPE_HINTS = {
    "service": ["service manual", "maintenance manual", "O&M manual", "IOM"],
    "installation": ["installation manual", "installation guide", "startup guide"],
    "controls": ["control manual", "operations manual", "user guide", "Touch Pilot manual"],
    "faults": ["fault code guide", "troubleshooting guide", "diagnostic manual"],
    "electrical": ["wiring diagram", "electrical schematic", "single-line diagram"],
}


def classify_risk(query: str) -> RiskLevel:
    """Classify the risk level of a query."""
    query_lower = query.lower()
    
    # Check high risk first
    for keyword in HIGH_RISK_KEYWORDS:
        if keyword in query_lower:
            return RiskLevel.HIGH
    
    # Check medium risk
    for keyword in MEDIUM_RISK_KEYWORDS:
        if keyword in query_lower:
            return RiskLevel.MEDIUM
    
    return RiskLevel.LOW


def classify_question_type(query: str) -> QuestionType:
    """
    Classify question type - CRITICAL for determining answer strategy.
    
    EXTRACTIVE (safe to summarize):
        - "What is the cooling capacity?"
        - "What are the water flow rates?"
        - "Which models are available?"
    
    PROCEDURAL (dangerous, never improvise):
        - "How do I recharge refrigerant?"
        - "How do I reset a safety trip?"
    """
    query_lower = query.lower()
    
    # =========================================================================
    # 1. EXTRACTIVE queries (SAFE - can summarize from tables)
    # =========================================================================
    extractive_patterns = [
        r"\bwhat\s+(is|are|does)\b",           # "What is the capacity?"
        r"\bwhich\s+\w+",                       # "Which models..."
        r"\bwhat\s+\w+\s+(does|do|is|are)\b",  # "What type does it use?"
        r"\blist\s+the\b",                      # "List the specifications"
        r"\btell\s+me\s+(about|the)\b",        # "Tell me about..."
        r"\bshow\s+me\b",                       # "Show me the specs"
        r"\bdescribe\b",                        # "Describe the..."
        r"\bexplain\s+the\b",                  # "Explain the features"
    ]
    
    # Keywords that indicate table-driven / spec questions
    extractive_keywords = [
        "capacity", "specifications", "specs", "rating", "ratings",
        "parameters", "features", "options", "models", "types",
        "range", "ranges", "limit", "limits", "requirement", "requirements",
        "what type", "what kind", "what model", "dimensions",
        "weight", "size", "voltage", "power", "efficiency",
    ]
    
    is_extractive = any(re.search(p, query_lower) for p in extractive_patterns)
    has_extractive_keywords = any(kw in query_lower for kw in extractive_keywords)
    
    if is_extractive or has_extractive_keywords:
        # But check for dangerous modifiers
        dangerous_extractive = ["how to", "procedure", "steps", "process"]
        if not any(d in query_lower for d in dangerous_extractive):
            return QuestionType.EXTRACTIVE
    
    # =========================================================================
    # 2. SAFETY PROCEDURE (NEVER improvise)
    # =========================================================================
    safety_keywords = [
        "lockout", "tagout", "loto", "energize", "de-energize",
        "override", "bypass", "emergency", "shutdown", "start up", "startup",
    ]
    # Also check regex patterns for safety procedures
    safety_patterns = [
        r"reset\s+\w*\s*safety", r"reset\s+\w*\s*trip",
        r"safety\s+trip", r"safety\s+reset",
    ]
    if any(kw in query_lower for kw in safety_keywords):
        return QuestionType.SAFETY_PROCEDURE
    if any(re.search(p, query_lower) for p in safety_patterns):
        return QuestionType.SAFETY_PROCEDURE
    
    # =========================================================================
    # 3. MECHANICAL PROCEDURE (dangerous physical work)
    # =========================================================================
    mechanical_keywords = [
        "charge", "recharge", "recover", "replace", "install", 
        "repair", "remove", "adjust", "calibrate", "rebuild",
        "disassemble", "reassemble", "add refrigerant", "evacuate",
    ]
    
    how_to_patterns = [
        r"\bhow\s+(do|can|to|should)\s+i?\b",
        r"\bprocedure\b", r"\bsteps?\s+(to|for)\b", r"\bprocess\s+for\b",
    ]
    is_how_to = any(re.search(p, query_lower) for p in how_to_patterns)
    
    if is_how_to:
        for kw in mechanical_keywords:
            if kw in query_lower:
                return QuestionType.MECHANICAL_PROCEDURE
    
    # =========================================================================
    # 4. DIAGNOSTIC (often answerable from specs + sensors)
    # =========================================================================
    diagnostic_keywords = [
        "troubleshoot", "diagnose", "verify", "check", "test", 
        "measure", "monitor", "read", "observe", "confirm",
    ]
    for kw in diagnostic_keywords:
        if kw in query_lower:
            return QuestionType.DIAGNOSTIC
    
    # =========================================================================
    # 5. NAVIGATION (UI/settings - usually safe)
    # =========================================================================
    navigation_keywords = [
        "access", "navigate", "find", "locate", "configure", 
        "set", "menu", "screen", "display", "setting",
    ]
    for kw in navigation_keywords:
        if kw in query_lower:
            return QuestionType.NAVIGATION
    
    # Default: if it's a "how" question we didn't catch, be cautious
    if is_how_to:
        return QuestionType.MECHANICAL_PROCEDURE
    
    # Otherwise it's probably extractive
    return QuestionType.EXTRACTIVE


def get_answer_strategy(question_type: QuestionType, risk_level: RiskLevel) -> AnswerStrategy:
    """
    Determine the answer strategy based on question type and risk.
    
    This is the permission switch for summarization.
    """
    # SAFE: Summarize from tables
    if question_type == QuestionType.EXTRACTIVE:
        return AnswerStrategy.SUMMARIZE
    
    # SAFE: Can extract + guide
    if question_type == QuestionType.NAVIGATION:
        return AnswerStrategy.EXTRACT
    
    # CAUTION: Provide orientation, not steps
    if question_type == QuestionType.DIAGNOSTIC:
        if risk_level == RiskLevel.HIGH:
            return AnswerStrategy.GUIDE
        return AnswerStrategy.EXTRACT
    
    # DANGER: Never improvise
    if question_type in [QuestionType.MECHANICAL_PROCEDURE, QuestionType.SAFETY_PROCEDURE]:
        return AnswerStrategy.REFUSE
    
    return AnswerStrategy.GUIDE


# ============================================================================
# CONFIDENCE SCORING
# ============================================================================

@dataclass
class ConfidenceScore:
    """Procedural confidence score with breakdown."""
    overall: float  # 0.0 - 1.0
    has_procedure: bool
    has_parameters: bool
    has_safety_info: bool
    known_manual_type: Optional[str] = None
    
    @property
    def mode(self) -> ResponseMode:
        """Determine response mode from confidence."""
        if self.has_procedure and self.overall >= 0.8:
            return ResponseMode.MODE_A
        elif self.has_parameters and self.overall >= 0.4:
            return ResponseMode.MODE_B
        elif self.known_manual_type:
            return ResponseMode.MODE_C
        else:
            return ResponseMode.MODE_D
    
    @property
    def tone(self) -> str:
        """Get the appropriate tone for responses."""
        if self.overall >= 0.8:
            return "confident"  # "Do X"
        elif self.overall >= 0.4:
            return "advisory"   # "You can check X"
        else:
            return "cautious"   # "Before proceeding, verify X"


def compute_confidence(
    query: str,
    retrieved_content: str,
    question_type: QuestionType
) -> ConfidenceScore:
    """Compute procedural confidence from retrieved content."""
    content_lower = retrieved_content.lower()
    
    # Check for procedure indicators
    procedure_patterns = [
        r"step\s*\d+", r"\d+\.\s+", r"procedure",
        r"first.*then", r"follow these steps",
    ]
    has_procedure = any(re.search(p, content_lower) for p in procedure_patterns)
    
    # Check for parameters
    param_patterns = [
        r"\d+\s*(psi|kpa|bar|°[fc]|gpm|l/s|cfm|kw|amp)",
        r"(min|max|range|limit).*\d+",
        r"setpoint", r"operating range",
    ]
    has_parameters = any(re.search(p, content_lower) for p in param_patterns)
    
    # Check for safety info
    safety_patterns = [
        r"safety", r"warning", r"caution", r"danger",
        r"lockout", r"tagout", r"protective",
    ]
    has_safety_info = any(re.search(p, content_lower) for p in safety_patterns)
    
    # Compute overall score
    score = 0.0
    if has_procedure:
        score += 0.5
    if has_parameters:
        score += 0.3
    if has_safety_info:
        score += 0.1
    
    # Bonus for content length (more context = more confidence)
    if len(retrieved_content) > 1000:
        score += 0.1
    
    # Penalty for dangerous question types without procedures
    if question_type == QuestionType.MECHANICAL_PROCEDURE and not has_procedure:
        score *= 0.5
    
    return ConfidenceScore(
        overall=min(score, 1.0),
        has_procedure=has_procedure,
        has_parameters=has_parameters,
        has_safety_info=has_safety_info
    )


# ============================================================================
# RANGE-BASED SUMMARIZATION
# ============================================================================

def extract_numeric_ranges(content: str) -> Dict[str, Dict[str, Any]]:
    """
    Extract numeric ranges from tabular/specification content.
    
    Returns dict of parameter_type -> {min, max, unit, count}
    """
    ranges = {}
    content_lower = content.lower()
    
    # Patterns for different parameter types
    patterns = {
        "capacity": r"(\d+(?:\.\d+)?)\s*(kw|tons?|tr|usrt|btu)",
        "flow_rate": r"(\d+(?:\.\d+)?)\s*(gpm|l/s|m³/h|l/min)",
        "pressure": r"(\d+(?:\.\d+)?)\s*(psi|kpa|bar|mpa)",
        "temperature": r"(\d+(?:\.\d+)?)\s*°?([fc]|celsius|fahrenheit)",
        "voltage": r"(\d+)\s*(v|volt|volts)",
        "power": r"(\d+(?:\.\d+)?)\s*(kw|hp|watts?)",
        "current": r"(\d+(?:\.\d+)?)\s*(a|amp|amps)",
        "efficiency": r"(\d+(?:\.\d+)?)\s*(cop|eer|iplv|%)",
    }
    
    for param_type, pattern in patterns.items():
        matches = re.findall(pattern, content_lower)
        if matches:
            values = [float(m[0]) for m in matches]
            unit = matches[0][1] if matches else ""
            ranges[param_type] = {
                "min": min(values),
                "max": max(values),
                "unit": unit.upper(),
                "count": len(values),
                "values": sorted(set(values))[:5]  # Keep unique values
            }
    
    return ranges


def format_range_summary(ranges: Dict[str, Dict[str, Any]], query: str) -> str:
    """
    Format extracted ranges into a natural language summary.
    
    This is the key function for range-based answering.
    """
    if not ranges:
        return ""
    
    query_lower = query.lower()
    lines = []
    
    # Prioritize ranges relevant to the query
    priority_map = {
        "capacity": ["capacity", "cooling", "kw", "tons", "size"],
        "flow_rate": ["flow", "gpm", "water"],
        "pressure": ["pressure", "psi"],
        "temperature": ["temperature", "temp", "°"],
        "voltage": ["voltage", "electrical", "power"],
        "power": ["power", "kw", "electrical"],
        "current": ["amp", "current", "electrical"],
        "efficiency": ["cop", "eer", "efficiency", "iplv"],
    }
    
    # Sort by relevance to query
    relevant_ranges = []
    other_ranges = []
    
    for param_type, data in ranges.items():
        keywords = priority_map.get(param_type, [])
        if any(kw in query_lower for kw in keywords):
            relevant_ranges.append((param_type, data))
        else:
            other_ranges.append((param_type, data))
    
    # Format relevant ranges first
    for param_type, data in relevant_ranges + other_ranges[:2]:
        param_name = param_type.replace("_", " ").title()
        
        if data["min"] == data["max"]:
            lines.append(f"• {param_name}: {data['min']} {data['unit']}")
        else:
            lines.append(f"• {param_name}: {data['min']} - {data['max']} {data['unit']}")
        
        if data["count"] > 5:
            lines[-1] += f" (across {data['count']} data points)"
    
    return "\n".join(lines)


def build_golden_fallback(
    query: str,
    content: str,
    equipment_name: str,
    question_type: QuestionType
) -> Dict[str, List[str]]:
    """
    Build the golden fallback structure.
    
    Returns:
        - what_document_contains
        - what_can_be_inferred
        - what_determines_exact_answer
        - what_arvis_needs_next
    """
    result = {
        "what_document_contains": [],
        "what_can_be_inferred": [],
        "what_determines_exact_answer": [],
        "what_arvis_needs_next": [],
    }
    
    content_lower = content.lower()
    
    # What the document contains
    if "performance" in content_lower or "capacity" in content_lower:
        result["what_document_contains"].append("Performance data and capacity specifications")
    if "electrical" in content_lower or "voltage" in content_lower:
        result["what_document_contains"].append("Electrical parameters and requirements")
    if "control" in content_lower or "touch pilot" in content_lower:
        result["what_document_contains"].append("Control system information")
    if "compressor" in content_lower:
        result["what_document_contains"].append("Compressor type and configuration")
    if "dimension" in content_lower or "weight" in content_lower:
        result["what_document_contains"].append("Physical dimensions and weight")
    
    # What can be inferred (range-based)
    ranges = extract_numeric_ranges(content)
    if ranges:
        for param_type, data in ranges.items():
            param_name = param_type.replace("_", " ")
            if data["min"] != data["max"]:
                result["what_can_be_inferred"].append(
                    f"{param_name.title()} varies from {data['min']} to {data['max']} {data['unit']}"
                )
    
    # What determines the exact answer
    if question_type == QuestionType.EXTRACTIVE:
        result["what_determines_exact_answer"] = [
            "Specific model number / size",
            "Operating conditions (ambient temp, load)",
            "Installed options and configuration",
        ]
    
    # What ARVIS needs next
    if question_type == QuestionType.EXTRACTIVE:
        result["what_arvis_needs_next"] = [
            "Confirm the specific model for exact values",
        ]
    elif question_type in [QuestionType.MECHANICAL_PROCEDURE, QuestionType.SAFETY_PROCEDURE]:
        result["what_arvis_needs_next"] = [
            "Service Manual for procedural steps",
            "Technician certification verification",
        ]
    
    return result


# ============================================================================
# STRUCTURED RESPONSE GENERATION
# ============================================================================

@dataclass
class StructuredResponse:
    """A structured response following the 4-mode pattern."""
    mode: ResponseMode
    confidence: ConfidenceScore
    risk_level: RiskLevel
    
    # Content sections
    main_answer: str = ""                    # The actual answer
    what_is_documented: List[str] = field(default_factory=list)
    what_is_missing: List[str] = field(default_factory=list)
    what_to_check: List[str] = field(default_factory=list)
    where_to_find: List[str] = field(default_factory=list)
    safety_notes: List[str] = field(default_factory=list)
    
    def format(self) -> str:
        """Format the response for display."""
        lines = []
        
        # Main answer
        if self.main_answer:
            lines.append(self.main_answer)
            lines.append("")
        
        # What is documented (Mode B, C, D)
        if self.what_is_documented and self.mode != ResponseMode.MODE_A:
            lines.append("**What is documented:**")
            for item in self.what_is_documented:
                lines.append(f"• {item}")
            lines.append("")
        
        # What to check next
        if self.what_to_check:
            lines.append("**Before proceeding:**")
            for item in self.what_to_check:
                lines.append(f"• {item}")
            lines.append("")
        
        # Where to find the answer
        if self.where_to_find:
            lines.append("**For detailed procedures:**")
            for item in self.where_to_find:
                lines.append(f"• {item}")
            lines.append("")
        
        # Safety notes (always last)
        if self.safety_notes:
            lines.append("⚠️ **Safety:**")
            for item in self.safety_notes:
                lines.append(f"• {item}")
        
        return "\n".join(lines)


def suggest_alternative_manuals(query: str, current_manual: str = "") -> List[str]:
    """Suggest which manuals likely contain the answer."""
    query_lower = query.lower()
    suggestions = []
    
    # Map query intent to manual types
    if any(kw in query_lower for kw in ["charge", "repair", "replace", "service"]):
        suggestions.append("Service Manual or O&M Manual")
    
    if any(kw in query_lower for kw in ["fault", "error", "alarm", "troubleshoot"]):
        suggestions.append("Troubleshooting Guide or Fault Code Reference")
    
    if any(kw in query_lower for kw in ["install", "startup", "commission"]):
        suggestions.append("Installation Manual or Startup Guide")
    
    if any(kw in query_lower for kw in ["control", "setting", "menu", "display"]):
        suggestions.append("Controls Manual or Operations Guide")
    
    if any(kw in query_lower for kw in ["wiring", "electrical", "circuit"]):
        suggestions.append("Electrical Schematics or Wiring Diagrams")
    
    if not suggestions:
        suggestions.append("Equipment-specific Service Manual")
    
    return suggestions


# ============================================================================
# MAIN RESPONSE BUILDER
# ============================================================================

def build_response(
    query: str,
    retrieved_content: str,
    retrieved_snippets: List[Dict[str, Any]],
    equipment_name: str = "this equipment",
    current_manual: str = ""
) -> StructuredResponse:
    """
    Build a confidence-aware structured response.
    
    This is the main entry point for generating ARVIS responses.
    """
    # Classify the query
    risk_level = classify_risk(query)
    question_type = classify_question_type(query)
    
    # Compute confidence
    confidence = compute_confidence(query, retrieved_content, question_type)
    mode = confidence.mode
    
    # Build response structure
    response = StructuredResponse(
        mode=mode,
        confidence=confidence,
        risk_level=risk_level
    )
    
    # Generate content based on mode
    if mode == ResponseMode.MODE_A:
        # We have a documented procedure
        response.main_answer = _generate_mode_a_answer(
            query, retrieved_content, equipment_name
        )
        
    elif mode == ResponseMode.MODE_B:
        # We have parameters but no procedure
        response.main_answer = (
            f"This documentation does not include a specific procedure for this task. "
            f"However, it provides operating parameters that can help assess the situation."
        )
        response.what_is_documented = _extract_documented_items(retrieved_content)
        response.what_to_check = _generate_checks(query, risk_level)
        
    elif mode == ResponseMode.MODE_C:
        # Point to other manuals
        response.main_answer = (
            f"This information is not included in the current documentation."
        )
        response.what_is_documented = _extract_documented_items(retrieved_content)
        response.where_to_find = suggest_alternative_manuals(query, current_manual)
        
    else:  # MODE_D
        # Escalation
        response.main_answer = (
            f"This procedure affects system safety and is not documented here. "
            f"Do not proceed without proper guidance."
        )
        response.what_to_check = _generate_safety_checks(query)
        response.where_to_find = suggest_alternative_manuals(query, current_manual)
        response.safety_notes = _generate_safety_notes(query, risk_level)
    
    return response


def _generate_mode_a_answer(query: str, content: str, equipment: str) -> str:
    """Generate a confident step-by-step answer for Mode A."""
    # This would ideally be enhanced by LLM
    return f"Based on the documentation for {equipment}:\n\n{content[:500]}"


def _extract_documented_items(content: str) -> List[str]:
    """Extract what IS documented from the retrieved content."""
    items = []
    content_lower = content.lower()
    
    # Check for various types of documented info
    if re.search(r"\d+\s*(psi|kpa|bar)", content_lower):
        items.append("Pressure specifications and limits")
    if re.search(r"\d+\s*°[fc]", content_lower):
        items.append("Temperature operating ranges")
    if re.search(r"\d+\s*(gpm|l/s|m³/h)", content_lower):
        items.append("Flow rate specifications")
    if re.search(r"\d+\s*(kw|amp|volt)", content_lower):
        items.append("Electrical parameters")
    if re.search(r"compressor", content_lower):
        items.append("Compressor type and configuration")
    if re.search(r"control|touch pilot", content_lower):
        items.append("Control system features")
    
    if not items:
        items.append("General equipment specifications")
    
    return items


def _generate_checks(query: str, risk_level: RiskLevel) -> List[str]:
    """Generate pre-procedure checks based on query and risk."""
    checks = []
    query_lower = query.lower()
    
    if "compressor" in query_lower:
        checks.append("Verify control power is available")
        checks.append("Check for active alarms on the control panel")
    
    if "pressure" in query_lower or "refrigerant" in query_lower:
        checks.append("Verify system is in safe state before accessing refrigerant circuit")
        checks.append("Check suction and discharge pressure readings")
    
    if "flow" in query_lower or "water" in query_lower:
        checks.append("Verify pump operation and flow switch status")
        checks.append("Check for any flow-related alarms")
    
    if risk_level == RiskLevel.HIGH:
        checks.insert(0, "Ensure lockout/tagout procedures are followed")
    
    if not checks:
        checks.append("Review current operating status before proceeding")
    
    return checks


def _generate_safety_checks(query: str) -> List[str]:
    """Generate safety-first checks for Mode D."""
    return [
        "Ensure lockout/tagout (LOTO) procedures are completed",
        "Verify system is de-energized before any work",
        "Confirm personal protective equipment is in use",
        "Review site-specific safety procedures",
    ]


def _generate_safety_notes(query: str, risk_level: RiskLevel) -> List[str]:
    """Generate safety notes based on the query."""
    notes = []
    query_lower = query.lower()
    
    if "refrigerant" in query_lower:
        notes.append("Refrigerant handling requires EPA 608 certification")
        notes.append("Never vent refrigerant to atmosphere")
    
    if "electrical" in query_lower or "voltage" in query_lower:
        notes.append("High voltage hazard - qualified personnel only")
    
    if "pressure" in query_lower:
        notes.append("High pressure systems can cause injury - use proper PPE")
    
    if risk_level == RiskLevel.HIGH and not notes:
        notes.append("This is a safety-critical procedure - follow manufacturer guidelines")
    
    return notes


# ============================================================================
# SYSTEM PROMPT FOR LLM
# ============================================================================

def get_arvis_system_prompt(mode: ResponseMode, confidence: ConfidenceScore) -> str:
    """Get the appropriate system prompt based on mode and confidence."""
    
    base = """You are ARVIS, an AI assistant for building operations technicians.

CORE PRINCIPLES:
- Never invent procedures that aren't documented
- Never stay silent when you have useful information
- Always move the technician forward with actionable guidance
"""
    
    if mode == ResponseMode.MODE_A:
        return base + """
MODE: DOCUMENTED PROCEDURE
You have found a documented procedure. Provide:
1. Clear step-by-step instructions from the documentation
2. Page/section references when available
3. Safety disclaimers only when the procedure requires them
Use confident language: "Do X", "Follow these steps"
"""
    
    elif mode == ResponseMode.MODE_B:
        return base + """
MODE: PARAMETERS + GUIDANCE
You don't have a specific procedure, but you have documented parameters.
1. Acknowledge you don't have step-by-step instructions
2. List the documented parameters, limits, and ranges
3. Explain what "normal" vs "abnormal" looks like
4. Suggest what to check based on these parameters
Use advisory language: "You can verify X", "Check that X is within range"
"""
    
    elif mode == ResponseMode.MODE_C:
        return base + """
MODE: CROSS-DOCUMENT HINT
The answer is likely in a different document. Provide:
1. What IS documented in the current source
2. Which manual/document typically contains this information
3. What section to look for
4. Offer to search other documents if available
Use helpful language: "This is typically covered in...", "You can find this in..."
"""
    
    else:  # MODE_D
        return base + """
MODE: ESCALATION
This is a safety-critical question you cannot answer safely. Provide:
1. Clear statement that you cannot provide this procedure
2. What safety checks must be done before proceeding
3. Where to find proper documentation
4. What NOT to do
Use cautious language: "Do not proceed without...", "Before attempting this..."
"""


def build_rag_prompt(
    query: str,
    context: str,
    equipment_name: str = "equipment"
) -> str:
    """
    Build the RAG prompt with engineering judgment scaffolding.
    
    This prompt grants 3 permissions:
    1. ENUMERATE: List what the documentation mentions
    2. SUMMARIZE RANGES: Describe bounds when data is tabular
    3. POINT-WITH-CONTEXT: Guide to specific pages/tables
    
    Args:
        query: The technician's question
        context: Retrieved documentation context
        equipment_name: Name of the equipment (e.g., "30XW chiller")
    
    Returns:
        The complete prompt for the LLM
    """
    # Classify the question to adjust permissions
    question_type = classify_question_type(query)
    risk_level = classify_risk(query)
    strategy = get_answer_strategy(question_type, risk_level)
    
    # Base prompt with engineering identity
    prompt = f"""You are ARVIS, a senior building systems engineer AI.

DOCUMENTATION CONTEXT:
{context}

TECHNICIAN'S QUESTION: {query}

"""
    
    # Add appropriate permissions based on strategy
    if strategy == AnswerStrategy.SUMMARIZE:
        prompt += """ANSWER PERMISSIONS (use engineering judgment):

1. ENUMERATE: When asked "what type/what are", list what the documentation mentions.
   Example: "The 30XW uses twin-rotor screw compressors (Key Features, page 4)."

2. SUMMARIZE RANGES: When data is in performance tables:
   - State that values vary by model/condition
   - Point to the specific pages
   Example: "Cooling capacity varies by model (pages 6-9). Values depend on operating conditions."

3. POINT-WITH-CONTEXT: Guide to the exact location.
   Example: "See page 7, select the row for your model. Flow rates scale with capacity."

BANNED PHRASES (never use these):
- "does not contain enough information"
- "for more details, please refer to"
- "the documentation does not provide"
- "I cannot determine"

REPLACEMENT PHRASES (use these instead):
- "values vary by model" 
- "exact selection depends on..."
- "see page X, table Y"

NEXT-ACTION HINTS (end your answer with one of these when appropriate):
- "If you know the model number, I can narrow this down."
- "For pump sizing, use the rated flow at nominal conditions."
- "Once you confirm the model, I can point you to the exact row."

Be confident, direct, and helpful. You are a senior engineer, not a search engine.
"""
    
    elif strategy == AnswerStrategy.EXTRACT:
        prompt += """ANSWER PERMISSIONS:

You may extract and present factual information from the documentation.
- List components, features, and specifications mentioned
- Reference specific pages and sections
- Explain what parameters are available

Be direct and informative. Use confident language.
"""
    
    elif strategy == AnswerStrategy.GUIDE:
        prompt += """ANSWER PERMISSIONS:

You may provide orientation and guidance, but NOT procedural steps.
- Explain what information exists and where
- Describe what determines the answer
- Point to the appropriate documentation

Use advisory language: "You can check...", "The documentation shows..."
"""
    
    else:  # REFUSE
        prompt += f"""ANSWER CONSTRAINTS:

This is a {risk_level.value}-risk procedural question. You must:
1. NOT provide improvised steps
2. Acknowledge what IS documented
3. Point to the correct manual/section
4. Recommend proper safety procedures

Use cautious language: "Before attempting this...", "Refer to the Service Manual for..."
"""
    
    return prompt


if __name__ == "__main__":
    # Demo
    print("ARVIS Response Modes Demo")
    print("=" * 50)
    
    test_queries = [
        "How do I recharge the refrigerant on a 30XW?",
        "What is the operating pressure range?",
        "How do I check the water flow rate?",
        "How do I access the control panel settings?",
    ]
    
    for query in test_queries:
        risk = classify_risk(query)
        qtype = classify_question_type(query)
        print(f"\nQuery: {query}")
        print(f"  Risk: {risk.value}")
        print(f"  Type: {qtype.value}")
