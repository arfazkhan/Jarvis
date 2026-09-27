"""The ARVIS FDD rule catalog."""

from agent_commercial.fdd.rules import ahu, plant, sensor, vav
from agent_commercial.fdd.rules.base import Param, RuleContext, RuleSpec, rules_by_id

RULES = [*sensor.RULES, *ahu.RULES, *vav.RULES, *plant.RULES]
RULES_BY_ID = rules_by_id(RULES)
SENSOR_RULE_IDS = [r.id for r in RULES if r.sensor_sweep]

__all__ = ["RULES", "RULES_BY_ID", "SENSOR_RULE_IDS", "Param", "RuleContext", "RuleSpec"]
