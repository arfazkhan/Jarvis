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
        """Send email notification via SMTP."""
        import os
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER")
        smtp_pass = os.environ.get("SMTP_PASS")
        recipient = os.environ.get("OPS_EMAIL_RECIPIENT", "ops@arvis.com")

        if not smtp_user or not smtp_pass:
            logger.warning(f"SMTP credentials missing. Would send email to {recipient}: {alert.title}")
            return
            
        try:
            msg = MIMEMultipart()
            msg['From'] = smtp_user
            msg['To'] = recipient
            msg['Subject'] = f"[ARVIS {alert.level.value.upper()}] {alert.title}"
            
            body = f"Source: {alert.source}\nTimestamp: {alert.timestamp}\n\nDetails:\n{alert.message}"
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
            server.quit()
            logger.info(f"Email sent successfully for alert: {alert.title}")
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
    def _send_sms(self, alert: Alert):
        # Mock SMS send
        print(f"SENDING SMS TO MANAGER: {alert.title}")
