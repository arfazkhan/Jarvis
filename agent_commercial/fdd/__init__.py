"""
ARVIS rule-based fault detection and diagnostics.

ASHRAE Guideline 36 rules ported from open-fdd (MIT — see NOTICE), run on
canonical point roles in SI, with ARVIS grounding rules: no assumed run state,
failed sensors invalidate rather than accuse, and every result is one of
PASS / FAIL / SKIP / INVALID with its reason.
"""

from agent_commercial.fdd.engine import FDDEngine, enrich_context  # noqa: F401
from agent_commercial.fdd.finding import FaultFinding, Outcome  # noqa: F401
from agent_commercial.fdd.frame import EquipmentFrame, build_frame  # noqa: F401
from agent_commercial.fdd.rules import RULES, RULES_BY_ID  # noqa: F401
