"""
Universal Equipment Model ID Detection
=======================================
Shared patterns for detecting, extracting, and expanding equipment model
identifiers across any HVAC/industrial equipment catalog.

Instead of hardcoding patterns for a single product line (e.g., Carrier 30XW),
this module provides a universal set of patterns that cover common naming
conventions used by major equipment manufacturers.
"""

import re
from typing import List, Tuple, Optional

# ═══════════════════════════════════════════════════════════════════════
# MODEL ID PATTERNS — ordered by specificity (most specific first)
# ═══════════════════════════════════════════════════════════════════════
# Each pattern is a compiled regex that matches a distinct model ID format.
# We test all patterns against any given text; a match means the text
# references a *specific* model, not a product family.

MODEL_ID_PATTERNS = [
    # ── Carrier-style: 4-digit numeric + optional letter suffix ──
    # Examples: 0312P, 1002, 2052S, 0502
    re.compile(r'\b(\d{4}[A-Z]?)\b'),

    # ── Series + variant: 2-3 digits + 2-3 letters + hyphen + letter(s) ──
    # Examples: 30XW-P, 30XA-S, 30RB-A, 19XR-PIC
    re.compile(r'\b(\d{2,3}[A-Z]{2,3}-[A-Z]{1,3})\b'),

    # ── York-style: 4 letters + 3-4 digits ──
    # Examples: YVAA0300, YLAA0200, YCIV0500
    re.compile(r'\b([A-Z]{4}\d{3,4})\b'),

    # ── Trane-style: 3-4 letters + hyphen + 3-4 digits ──
    # Examples: RTAC-400, CGAM-130, RTHD-300
    re.compile(r'\b([A-Z]{3,4}-\d{3,4})\b'),

    # ── Daikin-style: 4 letters + hyphen + letter(s) + optional digits ──
    # Examples: EWAD-B, EWAQ-BZ, EWYD-G06
    re.compile(r'\b([A-Z]{4}-[A-Z]{1,2}\d{0,3})\b'),

    # ── Generic alphanumeric with separator: LETTERS-DIGITS ──
    # Examples: AHU-350, FCU-200, VRF-2800, PAC-1200
    re.compile(r'\b([A-Z]{2,5}\d{3,5})\b'),

    # ── Mitsubishi/LG-style: mixed alpha-numeric model codes ──
    # Examples: PURY-P250, ARUN-080, PUHY-HP
    re.compile(r'\b([A-Z]{4}-[A-Z]?\d{2,4})\b'),
]

# ── Context words that indicate a following number is NOT a model ID ──
# If a 4-digit number is preceded by one of these words, it's likely a year,
# page reference, or section number — not an equipment model.
CONTEXT_DISQUALIFIERS = re.compile(
    r'(?:year|page|pages|section|figure|fig|table|edition|published|copyright|'
    r'since|circa|in|from|rev|revision|version|vol|volume)\s+$',
    re.IGNORECASE
)


# ═══════════════════════════════════════════════════════════════════════
# SERIES EXPANSION — fuzzy → canonical mapping
# ═══════════════════════════════════════════════════════════════════════
# Each entry: (regex_pattern, replacement_template)
# The regex captures the base and variant; the template produces the canonical form.
# This is applied to user queries to normalize model references before search.

SERIES_EXPANSIONS = [
    # Carrier 30XW series: "30XWP" or "30XW.P" or "30XW P" → "30XW-P"
    (re.compile(r'\b(30XW)[.\s]?([A-Z])\b', re.IGNORECASE), r'\1-\2'),
    # Carrier 30XA series
    (re.compile(r'\b(30XA)[.\s]?([A-Z])\b', re.IGNORECASE), r'\1-\2'),
    # Carrier 30RB/30RQ series
    (re.compile(r'\b(30R[BQ])[.\s]?([A-Z])\b', re.IGNORECASE), r'\1-\2'),
    # Carrier 19XR series
    (re.compile(r'\b(19XR)[.\s]?([A-Z]{1,3})\b', re.IGNORECASE), r'\1-\2'),
    # Generic: any DDLL pattern with missing hyphen → DD-LL
    # e.g., "30GX S" → "30GX-S"  (covers most Carrier series)
    (re.compile(r'\b(\d{2}[A-Z]{2})[.\s]([A-Z]{1,3})\b', re.IGNORECASE), r'\1-\2'),
]


def _is_contextual_false_positive(text: str, match_start: int) -> bool:
    """
    Check if a match at a given position is preceded by a context word
    that indicates it's a year/page/section reference, not a model ID.
    
    Examples:
        "published in 2024"  → True  (2024 is a year)
        "page 1002"          → True  (1002 is a page number)
        "model 1002"         → False (1002 is a model ID)
        "the 0312P chiller"  → False (0312P is a model ID)
    """
    preceding_text = text[:match_start]
    return bool(CONTEXT_DISQUALIFIERS.search(preceding_text))


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════

def has_specific_model(query: str) -> bool:
    """
    Returns True if the query contains a specific model identifier.
    Uses context-aware filtering: "page 1002" is ignored, "model 1002" is detected.
    
    Examples:
        "What is the COP for model 0312P?" → True  (Mode A)
        "What is the COP for the 30XW?"    → False (Mode B)
        "Tell me about YVAA0300"           → True  (Mode A)
        "Published in 2024"                → False (year, not model)
        "See page 1002"                    → False (page ref, not model)
    """
    if not query:
        return False
    
    for pattern in MODEL_ID_PATTERNS:
        for m in pattern.finditer(query):
            if not _is_contextual_false_positive(query, m.start()):
                return True
    return False


def extract_model_ids(text: str) -> List[str]:
    """
    Extract all model-like identifiers from raw text.
    Uses context-aware filtering to skip years, page numbers, etc.
    
    Returns a sorted, deduplicated list of model IDs found.
    """
    if not text:
        return []
    
    found = set()
    for pattern in MODEL_ID_PATTERNS:
        for m in pattern.finditer(text):
            value = m.group(1).upper().strip()
            if len(value) >= 3 and not _is_contextual_false_positive(text, m.start()):
                found.add(value)
    
    return sorted(found)


# ── Pattern for bare 4-digit numbers (the ambiguous ones) ──
_BARE_4DIGIT = re.compile(r'^\d{4}$')


def _is_ambiguous_match(match_text: str) -> bool:
    """
    Returns True if a model ID match is ambiguous (could be a year, quantity, etc.)
    
    Unambiguous matches (skip LLM):
        "0312P"   → has letter suffix → unambiguous
        "YVAA0300" → has letter prefix → unambiguous
        "30XW-P"  → has hyphen → unambiguous
        
    Ambiguous matches (need LLM):
        "1002"    → bare 4 digits → could be a model OR a quantity
    """
    return bool(_BARE_4DIGIT.match(match_text.strip()))


async def has_specific_model_verified(query: str, llm=None) -> bool:
    """
    Tiered model detection with LLM fallback for ambiguous matches.
    
    Tier 1 (instant): Structured patterns (letters + digits, hyphens) → accept
    Tier 2 (instant): Context disqualifiers ("page", "year", "in") → reject  
    Tier 3 (LLM):     Bare 4-digit numbers without context → ask LLM
    
    If no LLM is available, falls back to accepting the match (Tier 1 behavior).
    """
    if not query:
        return False
    
    ambiguous_candidates = []
    
    for pattern in MODEL_ID_PATTERNS:
        for m in pattern.finditer(query):
            if _is_contextual_false_positive(query, m.start()):
                continue  # Definitely not a model (preceded by "page", "year", etc.)
            
            match_text = m.group(1)
            if not _is_ambiguous_match(match_text):
                return True  # Unambiguous model ID (has letters, hyphens, etc.)
            
            ambiguous_candidates.append(match_text)
    
    if not ambiguous_candidates:
        return False  # No matches at all
    
    # ── Tier 3: LLM verification for ambiguous candidates ──
    if llm is None:
        return True  # No LLM available, accept the match (safe default)
    
    try:
        candidate_str = ", ".join(ambiguous_candidates)
        response = await llm.ask(
            messages=[{
                "role": "user",
                "content": (
                    f"In this query: \"{query}\"\n"
                    f"Are these specific equipment model numbers: {candidate_str}?\n"
                    "Answer ONLY 'yes' or 'no'. A model number identifies a specific "
                    "equipment unit (e.g., model 1002, unit 0502). "
                    "A quantity, year, measurement, or general number is NOT a model number."
                )
            }],
            system_msgs=[{
                "role": "system", 
                "content": "You are a classifier. Answer only 'yes' or 'no'."
            }],
            max_tokens=10
        )
        answer = (response.content or "").strip().lower()
        return answer.startswith("yes")
    except Exception:
        # LLM failed — fall back to accepting the match
        return True


def expand_query(query: str) -> str:
    """
    Normalize fuzzy model references in a query to their canonical forms.
    Used before vector search to improve retrieval accuracy.
    
    Examples:
        "30XWP cooling capacity"   → "30XWP cooling capacity 30XW-P"
        "30XW.S specifications"    → "30XW.S specifications 30XW-S"
    """
    expanded = query
    for pattern, replacement in SERIES_EXPANSIONS:
        matches = pattern.findall(query)
        for match_groups in matches:
            if isinstance(match_groups, tuple):
                canonical = pattern.sub(replacement, match_groups[0] + match_groups[1] if len(match_groups) > 1 else match_groups[0])
            else:
                canonical = pattern.sub(replacement, match_groups)
            # Use the pattern to reconstruct canonical form
            canonical_form = f"{match_groups[0].upper()}-{match_groups[1].upper()}" if isinstance(match_groups, tuple) and len(match_groups) > 1 else match_groups.upper()
            if canonical_form not in expanded:
                expanded += f" {canonical_form}"
    
    return expanded

