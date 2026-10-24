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
  media in POST {base}/chat/getBase64FromMediaMessage/{instance}
           body {"message": <the webhook's {key, message}>, "convertToMp4": false}
           → 201 {mediaType, fileName, caption, size, mimetype, base64}. Passing the
           whole received message (not just its key) works without Evolution's own
           message store. The webhook stays base64=false: media is fetched only for
           people on the roster, only when needed.
  groups   data.key.remoteJid is the group ("...@g.us"); the author is key.participant
           (key.participantAlt when that is an @lid). Mentions are jids in
           data.contextInfo.mentionedJid. The payload's top-level "sender" is the
           instance's own number (ARVIS's WhatsApp).

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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("arvis.messaging.evolution")

WEBHOOK_HEADER = "x-arvis-webhook-token"
WEBHOOK_EVENTS = ["MESSAGES_UPSERT", "MESSAGES_UPDATE"]
CHANNEL_NOTICE = ("WhatsApp messaging is provided through Evolution API "
                  "(https://github.com/evolution-foundation/evolution-api), licensed Apache-2.0.")


@dataclass
class InboundMessage:
    sender: str                 # phone number, digits only
    text: str                   # typed text, or Evolution's own voice transcript when it made one
    message_id: str
    reply_to: Optional[str]     # id of the message being replied to
    kind: str = "text"          # text | voice | image | document | video | other
    caption: str = ""           # an image's / document's caption
    media: Optional[Dict[str, Any]] = None   # {key, message} to fetch the media with (fetch_media)
    group: Optional[str] = None              # the group jid, for a message in the ops group
    mentions: List[str] = field(default_factory=list)   # jids @mentioned in it
    quoted_author: Optional[str] = None      # jid of the author of the message replied to
    own_jid: Optional[str] = None            # ARVIS's own WhatsApp (the instance's number)


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

    async def fetch_media(self, media: Dict[str, Any]) -> Tuple[bytes, str]:
        """The bytes and mimetype of a received image / voice note / document."""
        import base64
        out = await self._post(f"/chat/getBase64FromMediaMessage/{self.instance}",
                               {"message": media, "convertToMp4": False})
        b64 = out.get("base64")
        if not b64:
            raise EvolutionError(f"no media returned: {str(out)[:200]}")
        return base64.b64decode(b64), str(out.get("mimetype") or "")

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


_MEDIA_KINDS = (("audioMessage", "voice"), ("imageMessage", "image"), ("documentMessage", "document"),
                ("videoMessage", "video"), ("stickerMessage", "other"))


def ops_group() -> Optional[str]:
    """The site's ops group jid (ARVIS_OPS_GROUP), when group mode is on."""
    g = os.getenv("ARVIS_OPS_GROUP", "").strip()
    return g if g.endswith("@g.us") else None


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


def _kind_of(message: Dict[str, Any]) -> Tuple[str, str]:
    """(kind, caption) of a received message."""
    for key, kind in _MEDIA_KINDS:
        if isinstance(message.get(key), dict):
            return kind, str(message[key].get("caption") or "")
    return "text", ""


def parse_webhook(payload: Dict[str, Any], group: Optional[str] = None
                  ) -> Tuple[List[InboundMessage], List[DeliveryFailure]]:
    """Evolution webhook → inbound messages from people / delivery failures of ours.
    Group messages are kept only from the ops group (``group``, default ARVIS_OPS_GROUP)."""
    group = group if group is not None else ops_group()
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
            in_group = None
            if jid.endswith("@g.us"):
                if not group or jid != group:
                    continue                             # not the ops group
                in_group = jid
                jid = key.get("participant") or ""
                if "@lid" in jid and key.get("participantAlt"):
                    jid = key["participantAlt"]
            elif "@lid" in jid and key.get("remoteJidAlt"):
                jid = key["remoteJidAlt"]
            sender = _phone(jid)
            if sender is None:
                if jid.endswith("@lid"):
                    logger.info(f"[Evolution] message from unresolved LID {jid} — cannot match the roster; ignored")
                continue                                 # broadcast, or unknown addressing
            message = d.get("message") or {}
            ctx = d.get("contextInfo") or (message.get("extendedTextMessage") or {}).get("contextInfo") or {}
            kind, caption = _kind_of(message)
            messages.append(InboundMessage(
                sender=sender, text=_text_of(message), message_id=str(key.get("id") or ""),
                reply_to=ctx.get("stanzaId"), kind=kind, caption=caption,
                media={"key": key, "message": message} if kind != "text" else None,
                group=in_group, mentions=[str(j) for j in (ctx.get("mentionedJid") or []) if j],
                quoted_author=ctx.get("participant"), own_jid=payload.get("sender")))
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
