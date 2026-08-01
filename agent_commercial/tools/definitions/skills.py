"""
Compiled-Skill Tool Definitions
===============================

Runtime access to compiled equipment-manual skills (the CBI manual→skill
pipeline). Lets the agent load a compact, source-cited skill for a piece of
equipment instead of searching raw manuals.
"""

SKILL_TOOLS = [
    {
        "name": "load_equipment_skill",
        "description": (
            "Load the compiled manufacturer-manual skill for a piece of equipment "
            "to answer questions about faults, procedures, parameters, or safety. "
            "Returns the compact SKILL.md core (named fault frameworks, critical "
            "parameters with normal ranges, anti-patterns) and, when a topic is "
            "given, the relevant chapter. Every item cites its source manual "
            "page(s). Use this for 'what does fault X mean', 'startup procedure', "
            "'normal range for Y', 'maintenance steps' — it is grounded in the "
            "actual equipment manual, unlike general knowledge."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_key": {
                    "type": "string",
                    "description": "Compiled skill key (slug), e.g. 'otis-gen2-elevator'.",
                    "examples": ["otis-gen2-elevator"],
                },
                "equipment_id": {
                    "type": "string",
                    "description": "BMS equipment instance id, if the skill is bound to one.",
                    "examples": ["ELEV-01"],
                },
                "topic": {
                    "type": "string",
                    "description": "Optional functional area to load a specific chapter.",
                    "enum": ["fault-codes", "startup", "maintenance", "control-logic", "safety", "general"],
                    "examples": ["fault-codes"],
                },
            },
            "required": [],
        },
        "version": "1.0.0",
        "cost_class": "cheap",
        "precedents": [],
        "produces": ["evidence:compiled_skill"],
        "response_schema": {
            "type": "object",
            "properties": {
                "equipment_key": {"type": "string"},
                "status": {"type": "string"},
                "confidence": {"type": "number"},
                "skill_core": {"type": "string"},
                "chapter": {"type": "string"},
                "source_file": {"type": "string"},
                "available_skills": {"type": "array"},
            },
        },
    },
    {
        "name": "investigate_with_skills",
        "description": (
            "Route an alarm or investigation to the right compiled equipment skill "
            "and reason across systems. Given an alarm type or query (and optionally "
            "an equipment id), this resolves the equipment, classifies the topic, "
            "loads the relevant manual chapter, chains in the compiled skills of "
            "upstream/downstream dependent equipment for cross-system root-cause "
            "reasoning, and overlays this building's learned quirks (skillbook) on "
            "top of the manufacturer manual. Use for fault diagnosis and "
            "'why is X happening' investigations, not for a single lookup."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "string",
                    "description": "BMS equipment instance id at the center of the investigation.",
                    "examples": ["CH-02"],
                },
                "equipment_key": {
                    "type": "string",
                    "description": "Compiled skill key, if known.",
                    "examples": ["otis-gen2-elevator"],
                },
                "alarm_type": {
                    "type": "string",
                    "description": "Alarm type or symptom, e.g. 'high discharge temperature alarm'.",
                    "examples": ["high discharge temperature alarm"],
                },
                "query": {
                    "type": "string",
                    "description": "Natural-language investigation question.",
                    "examples": ["why does the elevator keep faulting on Mondays"],
                },
            },
            "required": [],
        },
        "version": "1.0.0",
        "cost_class": "medium",
        "precedents": [],
        "produces": ["evidence:skill_investigation"],
        "response_schema": {
            "type": "object",
            "properties": {
                "resolved": {"type": "boolean"},
                "primary": {"type": "object"},
                "chain": {"type": "array"},
                "learned_overlay": {"type": "array"},
                "available_skills": {"type": "array"},
                "notes": {"type": "array"},
            },
        },
    },
]
