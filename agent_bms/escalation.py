"""
Escalation Gateway
==================

Routes critical alerts to human operators.
Supports multi-channel notification (Email, SMS, Webhook).
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Optional

logger = logging.getLogger("arvis.escalation")

class EscalationLevel(Enum):
    INFO = "info"       # Log only
    WARNING = "warning" # Dashboard alert
    CRITICAL = "critical" # Email/SMS + Dashboard
    EMERGENCY = "emergency" # Phone Call + All Channels

@dataclass
class Alert:
    level: EscalationLevel
    title: str
    message: str
    source: str
    timestamp: str

class EscalationManager:
    def __init__(self, config=None):
        self.config = config or {}
        # self.email_client = EmailClient(config)
        # self.sms_client = SMSClient(config)
        
    def escalate(self, level: EscalationLevel, title: str, message: str, source="ARVIS_AGENT"):
        """
        Route the alert based on severity level.
        """
        alert = Alert(level, title, message, source, "now")
        logger.info(f"ESCALATION [{level.value.upper()}]: {title} - {message}")
        
        if level == EscalationLevel.INFO:
            self._log_alert(alert)
        elif level == EscalationLevel.WARNING:
            self._log_alert(alert)
            self._send_dashboard_alert(alert)
        elif level == EscalationLevel.CRITICAL:
            self._log_alert(alert)
            self._send_dashboard_alert(alert)
            self._send_email(alert)
        elif level == EscalationLevel.EMERGENCY:
            self._log_alert(alert)
            self._send_dashboard_alert(alert)
            self._send_email(alert)
            self._send_sms(alert)
            
    def _log_alert(self, alert: Alert):
        # Already logged via logger.info
        pass
        
    def _send_dashboard_alert(self, alert: Alert):
        # Push to frontend via websocket or DB
        print(f"DASHBOARD ALERT: {alert.title}")
        
    def _send_email(self, alert: Alert):
        # Mock email send
        print(f"SENDING EMAIL TO OPS TEAM: {alert.title}")
        
    def _send_sms(self, alert: Alert):
        # Mock SMS send
        print(f"SENDING SMS TO MANAGER: {alert.title}")
