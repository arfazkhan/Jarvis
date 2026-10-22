"""
Outbound network policy for on-prem deployments.

ARVIS sits on a building's BMS network. Whatever leaves that box is the site
owner's data, so on a live site outbound traffic must be explicit: the BMS LAN
(BACnet/Modbus, local services) is reachable, the internet is not — except for
the hosts the site has approved (typically one LLM endpoint).

Every outbound client in the codebase (OpenAI SDK, httpx, aiohttp, requests,
boto3) resolves its destination through ``socket.getaddrinfo``. Enforcing the
policy there covers all of them, including call sites added later, instead of
relying on each one to remember a check.

    ARVIS_EGRESS_POLICY = off (default) | enforce
    ARVIS_EGRESS_ALLOW  = comma-separated hostnames / domains / CIDRs
                          e.g. "api.k2think.ai, .openai.azure.com, 10.20.0.0/16"
                          A leading dot allows the domain and its subdomains.
                          Empty under `enforce` = nothing leaves the LAN
                          (the rule engine keeps working; LLM features degrade).

Under `enforce`:
  * IP literals are allowed when private / loopback / link-local (the BMS LAN)
    or inside an allowed CIDR; public IP literals are denied.
  * Hostnames are allowed when "localhost" or matching an ALLOW entry.
  * A denied destination raises ``socket.gaierror`` — the caller sees an
    ordinary resolution failure — and is logged once per host at WARNING,
    so a blocked LLM call is visible in the logs, never silent.

This is defence in depth for the application. The host firewall
(deploy/site/firewall.sh) is the outer layer and must be applied as well:
an app-level guard cannot stop code that bypasses getaddrinfo.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import socket
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

logger = logging.getLogger("arvis.egress")

_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_installed: Optional["EgressPolicy"] = None
_lock = threading.Lock()


@dataclass
class EgressPolicy:
    hosts: Set[str] = field(default_factory=set)        # exact hostnames
    domains: Set[str] = field(default_factory=set)      # ".example.com" suffixes (stored without the dot)
    networks: List[ipaddress._BaseNetwork] = field(default_factory=list)
    _warned: Set[str] = field(default_factory=set)

    @classmethod
    def from_allow_list(cls, raw: str) -> "EgressPolicy":
        policy = cls()
        for item in (raw or "").split(","):
            item = item.strip().lower().rstrip(".")
            if not item:
                continue
            try:
                policy.networks.append(ipaddress.ip_network(item, strict=False))
                continue
            except ValueError:
                pass
            if item.startswith("."):
                policy.domains.add(item[1:])
            else:
                policy.hosts.add(item)
        return policy

    def allows(self, host: str) -> Tuple[bool, str]:
        """Decide whether ``host`` may be contacted. Returns (allowed, reason)."""
        h = (host or "").strip().lower().rstrip(".")
        if h.startswith("[") and h.endswith("]"):
            h = h[1:-1]
        if not h:
            return True, "local (no host)"
        try:
            ip = ipaddress.ip_address(h.split("%", 1)[0])   # strip IPv6 zone id
        except ValueError:
            ip = None
        if ip is not None:
            if any(ip in net for net in self.networks):
                return True, "allowed CIDR"
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return True, "site LAN"
            return False, "public IP not on the allow list"
        if h == "localhost":
            return True, "localhost"
        if h in self.hosts:
            return True, "allowed host"
        if any(h == d or h.endswith("." + d) for d in self.domains):
            return True, "allowed domain"
        return False, "host not on the allow list"

    def summary(self) -> str:
        allow = sorted(self.hosts) + sorted("." + d for d in self.domains) + [str(n) for n in self.networks]
        return "enforce — site LAN + " + (", ".join(allow) if allow else "nothing else (no internet)")

    def _guarded_getaddrinfo(self, host, *args, **kwargs):
        name = host.decode() if isinstance(host, (bytes, bytearray)) else (host if host is not None else "")
        allowed, reason = self.allows(str(name))
        if not allowed:
            if name not in self._warned:
                self._warned.add(name)
                logger.warning(f"[Egress] blocked outbound connection to {name!r}: {reason} "
                               f"(ARVIS_EGRESS_POLICY=enforce). Add it to ARVIS_EGRESS_ALLOW if the site approved it.")
            raise socket.gaierror(socket.EAI_NONAME, f"egress blocked by ARVIS policy: {name} ({reason})")
        return _ORIGINAL_GETADDRINFO(host, *args, **kwargs)


def install_from_env() -> Optional[EgressPolicy]:
    """Install the policy if ARVIS_EGRESS_POLICY=enforce. Idempotent. Returns the active policy or None."""
    mode = os.getenv("ARVIS_EGRESS_POLICY", "off").strip().lower()
    if mode not in ("off", "enforce"):
        raise SystemExit(f"ARVIS_EGRESS_POLICY must be 'off' or 'enforce', got {mode!r}")
    if mode == "off":
        return None
    return install(EgressPolicy.from_allow_list(os.getenv("ARVIS_EGRESS_ALLOW", "")))


def install(policy: EgressPolicy) -> EgressPolicy:
    global _installed
    with _lock:
        socket.getaddrinfo = policy._guarded_getaddrinfo
        _installed = policy
    logger.info(f"[Egress] outbound policy: {policy.summary()}")
    return policy


def uninstall() -> None:
    global _installed
    with _lock:
        socket.getaddrinfo = _ORIGINAL_GETADDRINFO
        _installed = None


def active() -> Optional[EgressPolicy]:
    return _installed
