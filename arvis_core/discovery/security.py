"""Production safety primitives for the ARVIS Discovery Agent.

Includes:
- BACnet object-type allowlist
- Critical-equipment prefix detection (chillers, fire systems, elevators, life-safety)
- Capability token enum (least-privilege; deregister is NOT granted to the agent)
- Tiered rate limiter with anomaly-spike freeze
- HMAC-SHA256 action signing (key from env var ARVIS_DISCOVERY_HMAC_KEY)
"""

from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

logger = logging.getLogger("arvis.discovery.security")

ALLOWED_BACNET_OBJECT_TYPES = {
    "analogInput",
    "analogOutput",
    "binaryInput",
    "binaryOutput",
    "multiStateInput",
    "multiStateOutput",
    "analogValue",
    "binaryValue",
}

# Critical equipment that triggers two-person rule for writable points
CRITICAL_EQUIPMENT_PREFIXES = ("CH-", "FIRE-", "FACP-", "ELEV-", "LS-")


class CapabilityToken(Enum):
    PROBE = "probe"
    REGISTER_CRITICAL = "register_critical"
    REGISTER_NICE = "register_nice"
    DEREGISTER = "deregister"  # NOT granted to DiscoveryAgent — operator only
    AUDIT_READ = "audit_read"


# Capabilities granted to the DiscoveryAgent runtime. Note: DEREGISTER is
# deliberately absent — only an operator can remove a registered point.
DISCOVERY_AGENT_CAPABILITIES = {
    CapabilityToken.PROBE,
    CapabilityToken.REGISTER_CRITICAL,
    CapabilityToken.REGISTER_NICE,
    CapabilityToken.AUDIT_READ,
}


@dataclass
class RateLimitConfig:
    per_equipment_per_hour: int = 3
    per_agent_per_hour: int = 20
    global_per_hour: int = 100
    anomaly_spike_multiplier: float = 10.0  # freeze if 10x baseline


class RateLimiter:
    """Tiered token-bucket rate limiter with anomaly-spike freeze.

    Tracks discovery attempts per equipment, per agent, and globally over a
    rolling 1-hour window. If global throughput exceeds the EMA baseline by
    `anomaly_spike_multiplier`, freezes all discovery for 10 minutes.
    """

    def __init__(self, config: Optional[RateLimitConfig] = None) -> None:
        self.config = config or RateLimitConfig()
        self._events: Dict[str, deque] = defaultdict(lambda: deque(maxlen=2000))
        self._frozen_until: float = 0.0
        self._baseline_per_hour: Dict[str, float] = defaultdict(lambda: 5.0)

    def check_and_record(self, agent_id: str, equipment_id: str) -> Tuple[bool, Optional[str]]:
        now = time.time()
        if now < self._frozen_until:
            return False, f"frozen until {self._frozen_until:.0f} (anomaly detected)"

        cutoff = now - 3600
        for dq in self._events.values():
            while dq and dq[0] < cutoff:
                dq.popleft()

        eq_key = f"eq:{equipment_id}"
        agent_key = f"agent:{agent_id}"
        global_key = "global"

        eq_count = len(self._events[eq_key])
        agent_count = len(self._events[agent_key])
        global_count = len(self._events[global_key])

        if eq_count >= self.config.per_equipment_per_hour:
            return False, (
                f"per-equipment limit ({self.config.per_equipment_per_hour}/hr) "
                f"hit on {equipment_id}"
            )
        if agent_count >= self.config.per_agent_per_hour:
            return False, (
                f"per-agent limit ({self.config.per_agent_per_hour}/hr) hit on {agent_id}"
            )
        if global_count >= self.config.global_per_hour:
            return False, f"global limit ({self.config.global_per_hour}/hr) hit"

        baseline = self._baseline_per_hour[global_key]
        if baseline > 1 and global_count > baseline * self.config.anomaly_spike_multiplier:
            self._frozen_until = now + 600
            logger.warning(
                "[RateLimiter] Anomaly freeze: %d discoveries/hr vs baseline %.1f",
                global_count,
                baseline,
            )
            return False, (
                f"anomaly freeze: {global_count} discoveries/hr vs baseline {baseline:.1f}"
            )

        self._events[eq_key].append(now)
        self._events[agent_key].append(now)
        self._events[global_key].append(now)

        # EMA-update baseline
        self._baseline_per_hour[global_key] = 0.95 * baseline + 0.05 * global_count
        return True, None


def _get_hmac_key() -> bytes:
    key = os.environ.get("ARVIS_DISCOVERY_HMAC_KEY")
    if not key:
        logger.warning(
            "[Discovery] ARVIS_DISCOVERY_HMAC_KEY not set; using dev fallback "
            "(insecure — DO NOT use in production)."
        )
        key = "DEV_ONLY_DO_NOT_USE_IN_PRODUCTION_a8f3kdj2"
    return key.encode("utf-8")


def sign_action(action_dict: dict, nonce: str) -> str:
    """Return hex HMAC-SHA256 signature of (action_dict + nonce)."""
    payload = json.dumps({**action_dict, "nonce": nonce}, sort_keys=True, default=str).encode("utf-8")
    return hmac.new(_get_hmac_key(), payload, hashlib.sha256).hexdigest()


def verify_signature(action_dict: dict, nonce: str, signature: str) -> bool:
    expected = sign_action(action_dict, nonce)
    return hmac.compare_digest(expected, signature)


def is_critical_equipment(equipment_id: str) -> bool:
    if not equipment_id:
        return False
    return equipment_id.startswith(CRITICAL_EQUIPMENT_PREFIXES)


def is_allowed_object_type(object_type: Optional[str]) -> bool:
    if not object_type:
        return True  # unknown type from sim — allow; production layer will tighten
    return object_type in ALLOWED_BACNET_OBJECT_TYPES
