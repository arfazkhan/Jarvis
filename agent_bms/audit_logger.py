"""
Advisory Audit Logger
=====================

The "Black Box Recorder" for ARVIS.
Logs every advisory decision, data snapshot, and confidence score.
Ensures accountability and traceability for "Safety Veto" events.
"""

import json
import logging
import hashlib
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path

logger = logging.getLogger("arvis.audit")

class AdvisoryAuditLogger:
    def __init__(self, log_dir="logs/audit"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.current_log_file = self.log_dir / f"audit_{datetime.now().strftime('%Y%m')}.jsonl"

    def _compute_hash(self, data: Any) -> str:
        """Create a fingerprint of the input data state."""
        s = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(s.encode()).hexdigest()

    def log_decision(
        self,
        query: str,
        context: Dict[str, Any],
        tools_used: List[str],
        response: Dict[str, Any],
        confidence: float,
        owned_decision: str, # "Agent" or "Shared"
    ):
        """
        Record a decision event.
        """
        timestamp = datetime.now().isoformat()
        
        entry = {
            "timestamp": timestamp,
            "event_id": self._compute_hash(timestamp + query),
            "query": query,
            "data_snapshot_hash": self._compute_hash(context),
            "tools_executed": tools_used,
            "agent_response": response,
            "confidence_score": confidence,
            "owned_decision": owned_decision,
            "safety_veto": owned_decision == "Agent" and confidence > 0.9,
            "meta": {
                "model": "K2-Think", # Or dynamic
                "version": "1.0.0" 
            }
        }
        
        try:
            with open(self.current_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            logger.info(f"Audit log written: {entry['event_id']}")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    def get_recent_logs(self, limit=10) -> List[Dict]:
        """Retrieve recent logs for inspection."""
        logs = []
        if not self.current_log_file.exists():
            return []
            
        try:
            with open(self.current_log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines[-limit:]:
                    logs.append(json.loads(line))
        except Exception:
            pass
        return logs
