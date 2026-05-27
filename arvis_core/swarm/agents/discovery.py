"""DiscoveryAgent — swarm node specialized in autonomous BACnet point onboarding.

Responds to [BLIND_SPOT_DETECTED point=...] tags emitted during synthesis,
operator queries like "find FLT_DP on all AHUs", and audit queries.

The actual SwarmNode base class in this repo (arvis_core.swarm.node.SwarmNode)
is a pydantic BaseModel constructed via factory functions in
agent_commercial/swarm_nodes.py (name/role/tools fields). We mirror that
pattern via `build_discovery_agent()`.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from arvis_core.swarm.node import SwarmNode

logger = logging.getLogger("arvis.swarm.agents.discovery")


DISCOVERY_AGENT_NAME = "Discovery_Agent"

DISCOVERY_AGENT_ROLE = (
    "You are the ARVIS Discovery Agent — responsible for autonomous BACnet point "
    "onboarding. When the swarm detects a blind spot ([BLIND_SPOT_DETECTED point=X]) "
    "or the operator asks about missing/unmapped/new points, you:\n"
    "  1. Probe the point's BACnet metadata via probe_bacnet_point.\n"
    "  2. Classify it via the rule/ML hybrid classifier (criticality + cadence).\n"
    "  3. Register it into the runtime poll registry via register_point_to_poller, "
    "     OR escalate to operator approval for writable points on critical equipment.\n"
    "  4. Newly-registered points enter a 24h PROBATION period — values are read "
    "     but excluded from alarms until promotion.\n\n"
    "SAFETY CONSTRAINTS:\n"
    "  - Two-person rule for writable points on chillers (CH-*), fire systems "
    "    (FIRE-*, FACP-*), elevators (ELEV-*), and life-safety (LS-*).\n"
    "  - Rate-limited: max 3 discoveries/hr per equipment, 20/hr per agent, 100/hr global.\n"
    "  - Every action is signed (HMAC) and appended to an audit log.\n"
    "  - You CANNOT deregister points — only operators have that capability.\n\n"
    "RESPONSE STYLE:\n"
    "  - Be concise. Report what was discovered, classification, and the audit entry id.\n"
    "  - Use [DISCOVERY_REGISTERED] / [DISCOVERY_PENDING_APPROVAL] / [DISCOVERY_REJECTED] "
    "    prefix markers so downstream synthesis can detect outcomes.\n"
    "  - If a query asks for audit history, use audit_discovery_log."
)


def build_discovery_agent(tools_provider=None) -> SwarmNode:
    """Build the Discovery_Agent SwarmNode.

    `tools_provider` is an optional callable returning a list of tool dicts.
    Defaults to importing the EQUIPMENT_TOOLS list and filtering by name.
    """
    from agent_commercial.tools.definitions.equipment import EQUIPMENT_TOOLS

    wanted = {
        "get_point_inventory",
        "probe_bacnet_point",
        "register_point_to_poller",
        "list_discovery_candidates",
        "audit_discovery_log",
        "exclude_unreliable_sensor",
    }
    tools = [t for t in EQUIPMENT_TOOLS if t.get("name") in wanted]

    return SwarmNode(
        name=DISCOVERY_AGENT_NAME,
        llm_channel="tool",
        role=DISCOVERY_AGENT_ROLE,
        tools=tools,
    )


# ---- Helpers for queen synthesis hook --------------------------------------

_BLIND_SPOT_RE = re.compile(
    r"\[BLIND_SPOT_DETECTED\s+point=([\w/_\-\.]+)\]", re.IGNORECASE
)


def extract_blind_spot_point_ids(text: str) -> List[str]:
    """Extract point ids from `[BLIND_SPOT_DETECTED point=X]` tags in synthesis."""
    if not text:
        return []
    return _BLIND_SPOT_RE.findall(text)


async def dispatch_discoveries(
    point_ids: List[str], cap: int = 5
) -> List[Dict[str, Any]]:
    """Trigger discover_blind_spot for each id, capped at `cap` to prevent
    runaway dispatch within a single synthesis turn."""
    from arvis_core.discovery.service import get_discovery_service

    try:
        svc = get_discovery_service()
    except RuntimeError:
        logger.debug("[DiscoveryDispatch] service not initialized — skipping")
        return []

    results: List[Dict[str, Any]] = []
    for pid in point_ids[:cap]:
        try:
            decision = await svc.discover_blind_spot(pid, source="synthesis_hook")
            results.append(decision.to_dict())
        except Exception as e:
            logger.warning("[DiscoveryDispatch] dispatch failed for %s: %s", pid, e)
    return results
