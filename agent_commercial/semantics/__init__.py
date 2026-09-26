"""Semantic layer: canonical point roles, units and point-config import."""

from agent_commercial.semantics.point_roles import (  # noqa: F401
    PointRole,
    Quantity,
    ROLE_QUANTITY,
    RoleAssignment,
    PointRoleRegistry,
    equipment_kind,
    get_role_registry,
    parse_role,
    suggest_role,
    to_canonical,
)
