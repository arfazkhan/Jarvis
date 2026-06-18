"""Frontend-readiness endpoints: user/role auth, single-asset GET, create-one work
order, pagination, SSE route."""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager


@contextmanager
def _env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    os.environ.update({k: str(v) for k, v in kv.items()})
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _app():
    from fastapi.testclient import TestClient
    from arvisx.api import create_app
    return TestClient(create_app())


def test_open_mode_endpoints_asset_and_from_risk():
    with _env(ARVISX_DB=os.path.join(tempfile.mkdtemp(), "a.db")):
        c = _app()
        # single asset
        r = c.get("/api/v1/asset/BOOST-PUMP-01")
        assert r.status_code == 200 and r.json()["asset"]["asset_id"] == "BOOST-PUMP-01"
        assert c.get("/api/v1/asset/NOPE").status_code == 404

        # create ONE work order from the asset's risk
        r = c.post("/api/v1/workorders/from-risk", json={"asset_id": "BOOST-PUMP-01"})
        assert r.status_code == 200 and r.json()["asset_id"] == "BOOST-PUMP-01"
        wo_id = r.json()["wo_id"]
        # idempotent — same signature returns the same open WO
        r2 = c.post("/api/v1/workorders/from-risk", json={"asset_id": "BOOST-PUMP-01"})
        assert r2.json()["wo_id"] == wo_id


def test_pagination():
    with _env(ARVISX_DB=os.path.join(tempfile.mkdtemp(), "a.db")):
        c = _app()
        full = c.get("/api/v1/community/risks").json()
        one = c.get("/api/v1/community/risks?limit=1&offset=0").json()
        assert one["limit"] == 1 and len(one["risks"]) <= 1 and one["count"] == full["count"]


def test_sse_route_registered():
    with _env(ARVISX_DB=os.path.join(tempfile.mkdtemp(), "a.db")):
        app = __import__("arvisx.api", fromlist=["create_app"]).create_app()
        paths = {r.path for r in app.routes}
        assert "/api/v1/events/stream" in paths


def test_user_auth_and_role_gating():
    with _env(ARVISX_DB=os.path.join(tempfile.mkdtemp(), "a.db"),
              ARVISX_ADMIN_USER="boss", ARVISX_ADMIN_PASSWORD="s3cret",
              ARVISX_AUTH_SECRET="test-secret"):
        c = _app()
        # no creds → reads blocked once auth is on
        assert c.get("/api/v1/community/overview").status_code == 401

        # login as the bootstrapped owner
        r = c.post("/api/v1/auth/login", json={"username": "boss", "password": "s3cret"})
        assert r.status_code == 200 and r.json()["role"] == "owner"
        owner = {"Authorization": "Bearer " + r.json()["token"]}
        assert c.post("/api/v1/auth/login", json={"username": "boss", "password": "wrong"}).status_code == 401

        # owner can read + write
        assert c.get("/api/v1/community/overview", headers=owner).status_code == 200
        assert c.post("/api/v1/workorders/sync", headers=owner).status_code == 200
        assert c.get("/api/v1/auth/me", headers=owner).json()["role"] == "owner"

        # create a viewer; viewer can read but not write
        assert c.post("/api/v1/auth/users", headers=owner,
                      json={"username": "v", "password": "pw", "role": "viewer"}).status_code == 200
        vt = c.post("/api/v1/auth/login", json={"username": "v", "password": "pw"}).json()["token"]
        viewer = {"Authorization": "Bearer " + vt}
        assert c.get("/api/v1/community/risks", headers=viewer).status_code == 200
        assert c.post("/api/v1/workorders/sync", headers=viewer).status_code == 403


def test_field_pin_and_deeplink_token():
    """Technician field access: owner sets a PIN, the tech exchanges it for a
    technician-role token (PIN door), and a pre-minted deep-link token authes the
    same way (?t= door). Both can write entries; neither can manage."""
    with _env(ARVISX_DB=os.path.join(tempfile.mkdtemp(), "a.db"),
              ARVISX_ADMIN_USER="boss", ARVISX_ADMIN_PASSWORD="s3cret",
              ARVISX_AUTH_SECRET="test-secret"):
        c = _app()
        owner = {"Authorization": "Bearer " + c.post(
            "/api/v1/auth/login", json={"username": "boss", "password": "s3cret"}).json()["token"]}

        # roster a tech, then owner sets their PIN
        tid = c.post("/api/v1/technicians", headers=owner,
                     json={"name": "Ajith", "building": "one-anthem"}).json()["id"]
        assert c.post(f"/api/v1/technicians/{tid}/pin", headers=owner,
                      json={"pin": "4821"}).status_code == 200

        # PIN login is exempt from the auth wall (a tech has no token yet)
        bad = c.post("/api/v1/auth/field-login", json={"building": "one-anthem", "pin": "0000"})
        assert bad.status_code == 401
        ok = c.post("/api/v1/auth/field-login", json={"building": "one-anthem", "pin": "4821"})
        assert ok.status_code == 200 and ok.json()["role"] == "technician"
        tech = {"Authorization": "Bearer " + ok.json()["token"]}

        # technician identity resolves and can write (fills rounds) but can't manage users
        assert c.get("/api/v1/auth/me", headers=tech).json()["role"] == "technician"
        assert c.post("/api/v1/auth/users", headers=tech,
                      json={"username": "x", "password": "p", "role": "viewer"}).status_code == 403

        # deep-link door: owner mints a token for the tech; it authes the same way
        dt = c.post("/api/v1/auth/field-token", headers=owner, json={"technician": "Ajith"})
        assert dt.status_code == 200
        deep = {"Authorization": "Bearer " + dt.json()["token"]}
        assert c.get("/api/v1/auth/me", headers=deep).json()["role"] == "technician"

        # only managers can mint/set — a tech can't escalate
        assert c.post("/api/v1/auth/field-token", headers=tech,
                      json={"technician": "Ajith"}).status_code == 403


if __name__ == "__main__":
    test_open_mode_endpoints_asset_and_from_risk()
    test_pagination()
    test_sse_route_registered()
    test_user_auth_and_role_gating()
    test_field_pin_and_deeplink_token()
    print("PASS — frontend endpoints (auth/role, field PIN + deep-link token, asset, pagination, SSE) verified")
