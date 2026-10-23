"""
Evolution API transport for field checks
========================================

Evolution API (https://github.com/evolution-foundation/evolution-api) is a
self-hosted WhatsApp gateway. It runs next to ARVIS on the site box, so ARVIS
itself never talks to the internet for WhatsApp: it calls Evolution on the
local network and Evolution calls ARVIS's webhook back on it.

Evolution can drive WhatsApp two ways (chosen when the instance is created):
  WHATSAPP-BUSINESS   the official Cloud API (verified business number) — use this
                      for customer sites
  WHATSAPP-BAILEYS    WhatsApp Web automation — unofficial; the number can be
                      banned by WhatsApp
ARVIS is identical for both.

Shapes below are from Evolution's source (main, v2.3.x), not its docs, which
are out of date in places:
  send     POST {base}/message/sendText/{instance}  header apikey
           body {"number", "text"}  → 201, sent message id at key.id
  media    POST {base}/message/sendMedia/{instance}
           body {"number", "mediatype": image|document|video|audio, "mimetype",
           "media": URL or bare base64, "fileName", "caption", "delay"} → same shape
  webhook  POST to ARVIS: {event, instance, data, destination, date_time, sender,
           server_url, apikey}; event names are lower-dotted ("messages.upsert").
           Text and replies both arrive as data.message.conversation; the quoted
           message is described in top-level data.contextInfo. @lid senders are
           rewritten to their phone-number jid (key.remoteJidAlt) when known.
  set      POST {base}/webhook/set/{instance} {"webhook": {enabled, url, headers,
           byEvents, base64, events}}

Webhook authentication: Evolution does not sign webhooks, but it sends the
custom headers configured on the instance webhook. ARVIS configures a shared
secret header (ARVIS_EVOLUTION_WEBHOOK_TOKEN) and rejects calls without it.
Evolution retries failed webhooks, so inbound ids are de-duplicated upstream
(FieldCheckService).

Buttons are not used: on the Baileys integration WhatsApp does not render them
reliably. Checks ask for a typed YES / NO / NOT SURE.

License: Evolution API is Apache-2.0 with an added condition that the system
shows a notice that Evolution API is used, visible to administrators — see
CHANNEL_NOTICE (served by GET /api/v1/field-checks/channel).

Config (env):
  ARVIS_EVOLUTION_URL            e.g. http://127.0.0.1:8080
  ARVIS_EVOLUTION_INSTANCE       instance name
  ARVIS_EVOLUTION_APIKEY         instance (or global) API key
  ARVIS_EVOLUTION_WEBHOOK_TOKEN  shared secret Evolution sends back in x-arvis-webhook-token
"""

from __future__ import annotations

import argparse
import asyncio
import hmac
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("arvis.messaging.evolution")

WEBHOOK_HEADER = "x-arvis-webhook-token"
WEBHOOK_EVENTS = ["MESSAGES_UPSERT", "MESSAGES_UPDATE"]
CHANNEL_NOTICE = ("WhatsApp messaging is provided through Evolution API "
                  "(https://github.com/evolution-foundation/evolution-api), licensed Apache-2.0.")


@dataclass
class InboundMessage:
    sender: str                 # phone number, digits only
    text: str
    message_id: str
    reply_to: Optional[str]     # id of the message being replied to


@dataclass
class DeliveryFailure:
    message_id: str
    error: str


class EvolutionError(RuntimeError):
    pass


class EvolutionTransport:
    def __init__(self, base_url: str, instance: str, api_key: str, timeout: float = 15.0):
        if not base_url or not instance or not api_key:
            raise ValueError("base_url, instance and api_key are required")
        self.base_url = base_url.rstrip("/")
        self.instance = instance
        self._api_key = api_key
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> Optional["EvolutionTransport"]:
        url, inst, key = (os.getenv("ARVIS_EVOLUTION_URL", ""), os.getenv("ARVIS_EVOLUTION_INSTANCE", ""),
                          os.getenv("ARVIS_EVOLUTION_APIKEY", ""))
        if not (url and inst and key):
            return None
        return cls(url, inst, key)

    async def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        import httpx
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(f"{self.base_url}{path}", json=body, headers={"apikey": self._api_key})
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 400:
            err = data.get("error") if isinstance(data, dict) else None
            detail = (err or {}).get("message") if isinstance(err, dict) else (data.get("response") if isinstance(data, dict) else None)
            raise EvolutionError(f"HTTP {r.status_code}: {detail or r.text[:200]}")
        return data if isinstance(data, dict) else {}

    async def send_text(self, to: str, body: str, delay_ms: Optional[int] = None) -> str:
        """``delay_ms``: Evolution shows "typing…" for this long before sending —
        human pacing, and part of not looking like a bulk sender."""
        payload: Dict[str, Any] = {"number": to, "text": body}
        if delay_ms:
            payload["delay"] = int(delay_ms)
        data = await self._post(f"/message/sendText/{self.instance}", payload)
        msg_id = (data.get("key") or {}).get("id")
        if not msg_id:
            raise EvolutionError(f"send accepted but no message id returned: {str(data)[:200]}")
        return msg_id

    async def send_media(self, to: str, data: bytes, *, caption: str = "", filename: str = "chart.png",
                         mimetype: str = "image/png", delay_ms: Optional[int] = None) -> str:
        """An image (or document) as raw base64 — Evolution accepts a URL or bare base64
        (no data: prefix) in ``media``; ARVIS never exposes a URL for it to fetch."""
        import base64
        mediatype = "image" if mimetype.startswith("image/") else "document"
        payload: Dict[str, Any] = {"number": to, "mediatype": mediatype, "mimetype": mimetype,
                                   "media": base64.b64encode(data).decode("ascii"),
                                   "fileName": filename, "caption": caption}
        if delay_ms:
            payload["delay"] = int(delay_ms)
        out = await self._post(f"/message/sendMedia/{self.instance}", payload)
        msg_id = (out.get("key") or {}).get("id")
        if not msg_id:
            raise EvolutionError(f"media accepted but no message id returned: {str(out)[:200]}")
        return msg_id

    async def send_check(self, to: str, body: str, ref: str) -> str:
        return await self.send_text(to, body)

    async def configure_webhook(self, url: str, token: str) -> Dict[str, Any]:
        """Point the instance's webhook at ARVIS, with the shared-secret header."""
        return await self._post(f"/webhook/set/{self.instance}", {"webhook": {
            "enabled": True, "url": url, "headers": {WEBHOOK_HEADER: token},
            "byEvents": False, "base64": False, "events": WEBHOOK_EVENTS}})


def webhook_authorized(headers: Dict[str, str], token: Optional[str] = None) -> bool:
    expected = token if token is not None else os.getenv("ARVIS_EVOLUTION_WEBHOOK_TOKEN", "")
    got = headers.get(WEBHOOK_HEADER) or headers.get(WEBHOOK_HEADER.title()) or ""
    return bool(expected) and hmac.compare_digest(expected, got)


def _phone(jid: str) -> Optional[str]:
    """'97455501234@s.whatsapp.net' → '97455501234'. Groups and unresolved @lid → None."""
    user, _, server = (jid or "").partition("@")
    if server not in ("s.whatsapp.net", "c.us"):
        return None
    digits = "".join(ch for ch in user.split(":")[0] if ch.isdigit())
    return digits or None


def _text_of(message: Dict[str, Any]) -> str:
    """Typed text, a (legacy) button/list choice, or a voice-note transcript."""
    if not isinstance(message, dict):
        return ""
    for path in (("conversation",), ("extendedTextMessage", "text"),
                 ("buttonsResponseMessage", "selectedDisplayText"),
                 ("templateButtonReplyMessage", "selectedDisplayText"),
                 ("listResponseMessage", "title"), ("speechToText",)):
        v: Any = message
        for k in path:
            v = v.get(k) if isinstance(v, dict) else None
        if isinstance(v, str) and v.strip():
            return v
    return ""


def parse_webhook(payload: Dict[str, Any]) -> Tuple[List[InboundMessage], List[DeliveryFailure]]:
    """Evolution webhook → inbound messages from people / delivery failures of ours."""
    event = str(payload.get("event") or "").lower().replace("_", ".")
    data = payload.get("data")
    items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    messages: List[InboundMessage] = []
    failures: List[DeliveryFailure] = []
    if event == "messages.upsert":
        for d in items:
            key = d.get("key") or {}
            if key.get("fromMe"):
                continue                                 # typed on the business phone itself
            jid = key.get("remoteJid") or ""
            if "@lid" in jid and key.get("remoteJidAlt"):
                jid = key["remoteJidAlt"]
            sender = _phone(jid)
            if sender is None:
                if jid.endswith("@lid"):
                    logger.info(f"[Evolution] message from unresolved LID {jid} — cannot match the roster; ignored")
                continue                                 # group chat, broadcast, or unknown addressing
            ctx = d.get("contextInfo") or ((d.get("message") or {}).get("extendedTextMessage") or {}).get("contextInfo") or {}
            messages.append(InboundMessage(sender=sender, text=_text_of(d.get("message") or {}),
                                           message_id=str(key.get("id") or ""),
                                           reply_to=ctx.get("stanzaId")))
    elif event == "messages.update":
        for d in items:
            if str(d.get("status") or "").upper() == "ERROR" and (d.get("keyId") or d.get("key", {}).get("id")):
                failures.append(DeliveryFailure(message_id=str(d.get("keyId") or d["key"]["id"]),
                                                error="WhatsApp reported delivery ERROR"))
    return messages, failures


# ── one-off setup: python -m agent_commercial.messaging.evolution set-webhook --url ... ──
def _main() -> None:
    ap = argparse.ArgumentParser(description="Evolution API setup for ARVIS field checks")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("set-webhook", help="point the Evolution instance webhook at ARVIS")
    s.add_argument("--url", required=True, help="ARVIS webhook URL Evolution can reach, "
                                                "e.g. http://127.0.0.1:8000/api/v1/evolution/webhook")
    a = ap.parse_args()
    t = EvolutionTransport.from_env()
    token = os.getenv("ARVIS_EVOLUTION_WEBHOOK_TOKEN", "")
    if t is None or not token:
        raise SystemExit("Set ARVIS_EVOLUTION_URL, ARVIS_EVOLUTION_INSTANCE, ARVIS_EVOLUTION_APIKEY "
                         "and ARVIS_EVOLUTION_WEBHOOK_TOKEN first.")
    print(asyncio.run(t.configure_webhook(a.url, token)))


if __name__ == "__main__":
    _main()
