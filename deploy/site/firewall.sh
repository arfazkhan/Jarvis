#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# ARVIS edge box — host firewall (nftables). Outer layer of the site security.
# ═══════════════════════════════════════════════════════════════════════════════
# The box has two network interfaces:
#   BMS_IF   on the building's BMS network  → BACnet/IP, Modbus/TCP, OPC UA to BMS_NET only.
#                                            Nothing else in or out, ever.
#   MGMT_IF  on the management network      → operators reach the TLS proxy (443) and
#                                            SSH from MGMT_NET; outbound DNS + HTTPS only
#                                            (the approved LLM endpoint).
# The BMS network is never routed to the internet (forwarding is dropped).
#
# Which HTTPS *hosts* may be contacted is enforced inside ARVIS by
# ARVIS_EGRESS_POLICY / ARVIS_EGRESS_ALLOW (agent_commercial/egress_policy.py) —
# cloud LLM endpoints change IPs, so hostname filtering lives there, interface
# separation lives here. Use both.
#
# Usage (as root, on the edge host):
#   BMS_IF=eth1 BMS_NET=10.10.0.0/16 MGMT_IF=eth0 MGMT_NET=192.168.50.0/24 ./firewall.sh          # print only
#   BMS_IF=eth1 BMS_NET=10.10.0.0/16 MGMT_IF=eth0 MGMT_NET=192.168.50.0/24 ./firewall.sh --apply  # load it
#
# Review the printed ruleset with the site's IT team before --apply, and keep a
# console / out-of-band session open in case SSH is cut off.
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

: "${BMS_IF:?set BMS_IF (interface on the BMS network)}"
: "${BMS_NET:?set BMS_NET (BMS subnet, CIDR)}"
: "${MGMT_IF:?set MGMT_IF (interface on the management network)}"
: "${MGMT_NET:?set MGMT_NET (management subnet allowed to reach ARVIS, CIDR)}"
BACNET_PORT="${BACNET_PORT:-47808}"
MODBUS_PORT="${MODBUS_PORT:-502}"
OPCUA_PORT="${OPCUA_PORT:-4840}"

RULESET=$(cat <<EOF
table inet arvis {
  chain input {
    type filter hook input priority 0; policy drop;
    iif "lo" accept
    ct state established,related accept
    ct state invalid drop

    # BMS side: BACnet/IP replies and broadcasts (Who-Is / I-Am) from the BMS subnet only
    iifname "${BMS_IF}" ip saddr ${BMS_NET} udp dport ${BACNET_PORT} accept

    # Management side: TLS proxy, HTTP->HTTPS redirect, SSH — from the management subnet only
    iifname "${MGMT_IF}" ip saddr ${MGMT_NET} tcp dport { 22, 80, 443 } accept
    iifname "${MGMT_IF}" icmp type echo-request limit rate 5/second accept
  }

  chain forward {
    type filter hook forward priority 0; policy drop;   # never bridge the BMS network anywhere
  }

  chain output {
    type filter hook output priority 0; policy drop;
    oif "lo" accept
    ct state established,related accept

    # BMS side: read-only polling — BACnet/IP, Modbus/TCP and OPC UA to the BMS subnet, nothing else
    oifname "${BMS_IF}" ip daddr ${BMS_NET} udp dport ${BACNET_PORT} accept
    oifname "${BMS_IF}" ip daddr ${BMS_NET} tcp dport ${MODBUS_PORT} accept
    oifname "${BMS_IF}" ip daddr ${BMS_NET} tcp dport ${OPCUA_PORT} accept
    oifname "${BMS_IF}" ip daddr 255.255.255.255 udp dport ${BACNET_PORT} accept
    oifname "${BMS_IF}" udp sport ${BACNET_PORT} udp dport ${BACNET_PORT} accept

    # Management side: DNS, HTTPS (LLM endpoint, host-filtered by ARVIS_EGRESS_ALLOW; WhatsApp
    # for the Evolution API container, which runs outside ARVIS's egress policy), NTP
    oifname "${MGMT_IF}" udp dport { 53, 123 } accept
    oifname "${MGMT_IF}" tcp dport { 53, 443 } accept
  }
}
EOF
)

echo "$RULESET"
if [[ "${1:-}" == "--apply" ]]; then
  nft list table inet arvis >/dev/null 2>&1 && nft delete table inet arvis
  echo "$RULESET" | nft -f -
  sysctl -w net.ipv4.ip_forward=0 >/dev/null
  echo "ARVIS firewall applied. Persist it with your distro's nftables service (e.g. /etc/nftables.conf)."
else
  echo
  echo "Printed only. Re-run with --apply to load it."
fi
