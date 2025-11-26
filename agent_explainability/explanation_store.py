"""
Explanation Store
-----------------
Logs reasoning traces for agent decisions.
Used for "Why did you do that?" queries and UI transparency.
"""

import time
from typing import Dict, Any, List

class ExplanationStore:
    def __init__(self):
        self.logs: List[Dict[str, Any]] = []

    def log(self, source: str, decision: str, reason: str, context: Dict[str, Any] = None):
        """
        Log an explanation.
        :param source: Component name (e.g., "AdaptivePlanEngine")
        :param decision: What was decided (e.g., "Set brightness to 30%")
        :param reason: Why (e.g., "User preference override")
        :param context: Additional data
        """
        entry = {
            "timestamp": time.time(),
            "source": source,
            "decision": decision,
            "reason": reason,
            "context": context or {}
        }
        self.logs.append(entry)
        # Keep last 100 logs
        if len(self.logs) > 100:
            self.logs.pop(0)

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        return sorted(self.logs, key=lambda x: x["timestamp"], reverse=True)[:limit]
