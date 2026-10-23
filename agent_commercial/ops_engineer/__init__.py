"""
ARVIS on WhatsApp — the building's 24/7 operations engineer.
============================================================

Not a menu bot: the facilities team talks to ARVIS the way they talk to a
senior engineer. It remembers the conversation, reasons from live building
data, takes the actions it is asked for (ask a technician to check something,
record a repair), and speaks up on its own when something matters — so the
team does not need the dashboard day to day; it opens it only for a deep look.

  people.py     who is who (phone number → name, role, language)
  memory.py     persisted conversation threads + what ARVIS already told whom
  engineer.py   one conversational turn: context → reasoning with tools → grounded reply
  gateway.py    inbound WhatsApp → field-check answers or the engineer; outbound pacing
  proactive.py  events (confirmed faults, repairs verified/failed) + morning brief → who needs to know

Read-only towards the building, like all of ARVIS: actions change ARVIS's own
records (checks, repairs to verify), never equipment.
"""

from typing import Any, Optional

_gateway: Optional[Any] = None


def set_gateway(gateway: Any) -> None:
    global _gateway
    _gateway = gateway


def get_gateway() -> Optional[Any]:
    """The running WhatsApp gateway, or None when the ops engineer is not configured."""
    return _gateway
