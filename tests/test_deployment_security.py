"""
Deployment security regression tests.

1. ARVIS is read-only towards the building: no code path may issue a BACnet or
   Modbus write. Enforced here by scanning the runtime packages' syntax trees,
   so adding a write path fails the build instead of shipping quietly.
2. The outbound (egress) policy blocks the internet except approved hosts.
3. The deployment files keep their hardening: loopback API behind a TLS proxy on
   site, egress enforced, no default passwords, no open Prometheus lifecycle API.
"""
import ast
import logging
import pathlib
import socket

import pytest
import yaml

from agent_commercial import egress_policy
from agent_commercial.egress_policy import EgressPolicy

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME_PACKAGES = ["agent_commercial", "arvis_core", "agent_unified"]

# BACnet write services and Modbus write functions (pymodbus + bacpypes3 spellings)
WRITE_APIS = {
    "write_property", "write_property_multiple", "WritePropertyRequest", "WritePropertyMultipleRequest",
    "WriteProperty", "WritePropertyMultiple", "write_group", "WriteGroupRequest",
    "write_register", "write_registers", "write_coil", "write_coils",
    "mask_write_register", "readwrite_registers", "write_file_record",
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Read-only towards the building
# ─────────────────────────────────────────────────────────────────────────────
def _runtime_sources():
    for pkg in RUNTIME_PACKAGES:
        for path in (ROOT / pkg).rglob("*.py"):
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            yield path


def test_no_bms_write_calls_anywhere_in_runtime_code():
    offenders = []
    for path in _runtime_sources():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            name = (node.attr if isinstance(node, ast.Attribute)
                    else node.id if isinstance(node, ast.Name)
                    else node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    else None)
            if name in WRITE_APIS:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} uses {name}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name.split(".")[-1] in WRITE_APIS:
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} imports {alias.name}")
    assert not offenders, "ARVIS must stay read-only towards the BMS:\n" + "\n".join(offenders)


def test_the_scan_actually_catches_a_write(tmp_path):
    """Guard against the scanner silently matching nothing."""
    tree = ast.parse("client.write_register(1, 2)\nfrom bacpypes3.apdu import WritePropertyRequest\n")
    found = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    found |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert {"write_register", "WritePropertyRequest"} <= found & WRITE_APIS


# ─────────────────────────────────────────────────────────────────────────────
# 2. Egress policy
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _restore_resolver():
    yield
    egress_policy.uninstall()


def test_site_lan_and_loopback_always_reachable():
    p = EgressPolicy.from_allow_list("")
    for host in ("10.10.4.20", "192.168.1.100", "172.16.0.5", "127.0.0.1", "::1", "localhost", "169.254.1.1"):
        assert p.allows(host)[0], host


def test_internet_blocked_unless_allowed():
    p = EgressPolicy.from_allow_list("api.k2think.ai, .openai.azure.com, 203.0.113.0/24")
    assert p.allows("api.k2think.ai")[0]
    assert p.allows("API.K2THINK.AI.")[0]                      # case + trailing dot
    assert p.allows("qatar.openai.azure.com")[0]               # domain suffix
    assert p.allows("openai.azure.com")[0]
    assert p.allows("203.0.113.9")[0]                          # allowed CIDR
    assert not p.allows("api.groq.com")[0]
    assert not p.allows("evil-openai.azure.com.attacker.net")[0]
    assert not p.allows("notopenai.azure.com.evil")[0]
    assert not p.allows("8.8.8.8")[0]                          # public IP literal


def test_enforced_resolver_blocks_and_logs_once(caplog):
    egress_policy.install(EgressPolicy.from_allow_list("localhost"))
    caplog.set_level(logging.WARNING, logger="arvis.egress")
    for _ in range(2):
        with pytest.raises(socket.gaierror):
            socket.getaddrinfo("api.groq.com", 443)
    blocked = [r for r in caplog.records if "api.groq.com" in r.getMessage()]
    assert len(blocked) == 1                                    # visible, but not log spam
    assert socket.getaddrinfo("127.0.0.1", 80)                  # LAN / loopback still resolves


def test_uninstall_restores_resolver():
    egress_policy.install(EgressPolicy.from_allow_list(""))
    assert socket.getaddrinfo is not egress_policy._ORIGINAL_GETADDRINFO
    egress_policy.uninstall()
    assert socket.getaddrinfo is egress_policy._ORIGINAL_GETADDRINFO


def test_install_from_env(monkeypatch):
    monkeypatch.setenv("ARVIS_EGRESS_POLICY", "off")
    assert egress_policy.install_from_env() is None
    monkeypatch.setenv("ARVIS_EGRESS_POLICY", "enforce")
    monkeypatch.setenv("ARVIS_EGRESS_ALLOW", "api.k2think.ai")
    policy = egress_policy.install_from_env()
    assert policy is egress_policy.active() and policy.allows("api.k2think.ai")[0]
    monkeypatch.setenv("ARVIS_EGRESS_POLICY", "maybe")
    with pytest.raises(SystemExit):
        egress_policy.install_from_env()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Deployment configuration
# ─────────────────────────────────────────────────────────────────────────────
def _env(service):
    return dict(item.split("=", 1) for item in service.get("environment", []))


def test_site_compose_keeps_api_off_the_bms_network():
    site = yaml.safe_load((ROOT / "docker-compose.site.yml").read_text(encoding="utf-8"))
    arvis, proxy = site["services"]["arvis"], site["services"]["proxy"]
    env = _env(arvis)
    assert env["ARVIS_API_HOST"] == "127.0.0.1"
    assert env["ARVIS_EGRESS_POLICY"] == "enforce"
    assert "ARVIS_MGMT_IP" in _env(proxy) and ":?" in _env(proxy)["ARVIS_MGMT_IP"]
    template = (ROOT / "nginx" / "site.conf.template").read_text(encoding="utf-8")
    listens = [line.strip() for line in template.splitlines() if line.strip().startswith("listen")]
    assert listens and all("${ARVIS_MGMT_IP}" in line for line in listens)
    assert "proxy_pass http://127.0.0.1:8000" in template


def test_main_compose_has_no_default_passwords_or_open_admin_ports():
    raw = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "arvis123" not in raw
    assert "GRAFANA_PASSWORD:-" not in raw
    assert "web.enable-lifecycle" not in raw
    compose = yaml.safe_load(raw)
    for name, svc in compose["services"].items():
        for port in svc.get("ports", []):
            if name == "nginx":                                 # the intended public entry point
                continue
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} on all interfaces"


def test_api_bind_host_comes_from_env(monkeypatch):
    import uvicorn
    from agent_commercial.api import routes
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port: seen.update(host=host))
    monkeypatch.setattr(routes, "create_api", lambda: object())
    monkeypatch.setenv("ARVIS_API_HOST", "127.0.0.1")
    routes.run_server()
    assert seen["host"] == "127.0.0.1"
