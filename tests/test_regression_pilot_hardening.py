"""
Regression tests for the pre-pilot hardening fixes.

Locks in the grounding + security defects fixed in commits c6e1b83, 5ac5207,
1d2f6a68, 41e88ed5, ce811a34 so they can't silently come back:

  * briefings never fabricate findings for a real building (demo seeding is
    opt-in only)
  * JWT auth enforces expiry on EVERY request and never caches tokens
  * both logins fail closed when no password is configured
  * the draft-export endpoint confines writes to a safe directory
"""
import os
import asyncio
from datetime import datetime, timedelta

import pytest


# ── Grounding: briefings must not fabricate for real buildings ────────────────

def _make_generator(demo_env):
    if demo_env is None:
        os.environ.pop("ARVIS_DEMO_BRIEFING", None)
    else:
        os.environ["ARVIS_DEMO_BRIEFING"] = demo_env
    from agent_commercial.briefing_engine import BriefingGenerator
    # No alarm_engine / energy / skillbook → nothing real to report.
    return BriefingGenerator(building_id="default")


def test_briefing_no_fabrication_by_default():
    """A real 'default' building with no data yields ZERO invented findings."""
    gen = _make_generator(demo_env=None)
    assert gen.demo_seed is False
    since = datetime.now() - timedelta(hours=8)
    critical, attention = gen._detect_anomalies(since)
    wins = gen._calculate_wins(since)
    # None of the old hardcoded demo items may appear.
    banned = {"FLOOR-23", "AHU-19", "CH-04", "CHW-PUMP-02"}
    seen_ids = {getattr(i, "equipment_id", "") for i in (critical + attention)}
    assert not (seen_ids & banned), f"fabricated items leaked: {seen_ids & banned}"
    assert critical == [] and attention == []
    assert wins == [], "fabricated 'QAR 127' win leaked into a real building"


def test_briefing_demo_seed_opt_in():
    """With ARVIS_DEMO_BRIEFING=1 the scripted demo content IS produced."""
    gen = _make_generator(demo_env="1")
    assert gen.demo_seed is True
    critical, attention = gen._detect_anomalies(datetime.now() - timedelta(hours=8))
    assert critical or attention, "demo seeding should populate items when opt-in"
    os.environ.pop("ARVIS_DEMO_BRIEFING", None)


# ── Security: JWT expiry enforced every call, never cached ────────────────────

def test_jwt_expiry_enforced_and_not_cached():
    os.environ["ARVIS_AUTH_SECRET"] = "regression-secret"
    from agent_commercial.api.auth import create_access_token
    from api import security

    expired = create_access_token({"sub": "admin", "role": "admin"},
                                  expires_delta=timedelta(seconds=-5))
    assert security._resolve_role(expired) is None          # rejected
    assert security._resolve_role(expired) is None          # still rejected (not cached)
    assert expired not in security.API_KEYS                 # never cached

    valid = create_access_token({"sub": "admin", "role": "admin"},
                                expires_delta=timedelta(minutes=5))
    from api.security import Role
    assert security._resolve_role(valid) == Role.ADMIN
    assert valid not in security.API_KEYS                   # valid tokens not cached either


def test_fixed_pilot_token_rejected():
    """The removed password-free backdoor string must not authenticate."""
    os.environ["ARVIS_AUTH_SECRET"] = "regression-secret"
    from api import security
    assert security._resolve_role("pilot_admin_token") is None
    assert security._resolve_role("pilot_operator_token") is None


# ── Security: logins fail closed when unconfigured ────────────────────────────

def test_generic_login_requires_password():
    from fastapi import HTTPException
    from api.routers import auth as router_auth
    # no password configured for 'operator'
    for var in ("ARVIS_OPERATOR_PASSWORD", "ARVIS_OPERATOR_PASS"):
        os.environ.pop(var, None)
    with pytest.raises(HTTPException):
        asyncio.run(router_auth.login_for_access_token(
            router_auth.LoginRequest(username="operator", password="")))
    # configured → succeeds
    os.environ["ARVIS_ADMIN_PASSWORD"] = "pw123"
    os.environ["ARVIS_AUTH_SECRET"] = "regression-secret"
    out = asyncio.run(router_auth.login_for_access_token(
        router_auth.LoginRequest(username="admin", password="pw123")))
    assert out["token_type"] == "bearer" and out["access_token"]
    # wrong password → rejected
    with pytest.raises(HTTPException):
        asyncio.run(router_auth.login_for_access_token(
            router_auth.LoginRequest(username="admin", password="nope")))
    os.environ.pop("ARVIS_ADMIN_PASSWORD", None)


# ── Security: draft export path confinement ───────────────────────────────────

@pytest.mark.parametrize("evil", [
    "../../../../Windows/System32/evil.yaml",
    r"C:\Windows\hax.yaml",
    "/etc/passwd",
    "a/b/c.yml",
])
def test_draft_path_confined(evil):
    from agent_commercial.api.routes_demo import _safe_draft_path
    base, safe = _safe_draft_path(evil)
    assert base.resolve() in safe.parents, f"{evil} escaped the drafts dir"
    assert safe.name == __import__("pathlib").Path(evil).name.replace("\\", "/").split("/")[-1] \
        or safe.suffix in (".yaml", ".yml")
