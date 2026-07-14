"""
The brain — durable project memory + semantic recall.

Two ways things get remembered:
  1. Someone SAYS so   — "remember the client wants matte finish" → a memory, verbatim.
  2. Every day is closed out — the end-of-day summary is itself stored as a memory.

Recall runs over BOTH the memories and every message ever sent in the group, by MEANING —
so "what did we decide about the pump six months ago" finds it even if nobody used the word
"pump" the same way. Embeddings are the pluggable, admin-configurable ArvisX ones; with no
embeddings provider configured it degrades to keyword search (worse, never broken).

Nothing here fabricates: recall only ranks and returns real stored text, with its date.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# "remember X" — the explicit save. Kept deliberately broad (site teams type fast, mixed-script).
_REMEMBER_RE = re.compile(
    r"^\s*(?:@?firstbriq[,:\s]+)?(?:please\s+)?"
    r"(?:remember|note this|note that|make a note|log this|keep in mind|yaad rakh(?:na|o)?|"
    r"don'?t forget)\b[:\-,\s]*(.+)$", re.I | re.S)

# "what did we say about X" — the explicit recall.
_RECALL_RE = re.compile(
    r"\b(?:what (?:did|do) we (?:say|discuss|decide|agree)|when did we|"
    r"did we (?:ever )?(?:discuss|decide|agree|talk)|recall|remind me (?:about|what)|"
    r"search|find|look ?up|any(?:thing)? about)\b", re.I)
_TOPIC_RE = re.compile(r"\b(?:about|regarding|on|for|re)\s+(.+?)[?.!]*$", re.I)

_STOP = {"the", "a", "an", "we", "our", "did", "was", "were", "is", "are", "about", "on", "for",
         "of", "to", "and", "that", "this", "with", "in", "it", "what", "when", "say", "said",
         "discuss", "discussed", "decide", "decided", "ever", "anything", "me"}


def remember_request(text: str) -> str:
    """'remember X' → X (the thing to store). '' if this isn't a remember instruction."""
    m = _REMEMBER_RE.match((text or "").strip())
    if not m:
        return ""
    what = m.group(1).strip().strip('"“”')
    return what if len(what) >= 4 else ""


def recall_request(text: str) -> str:
    """'what did we say about the countertop' → 'the countertop'. '' if not a recall question."""
    s = (text or "").strip()
    if not _RECALL_RE.search(s):
        return ""
    m = _TOPIC_RE.search(s)
    topic = m.group(1).strip() if m else ""
    if not topic:                       # no "about X" → strip the question words, keep the rest
        topic = re.sub(_RECALL_RE, "", s).strip(" ?.!,")
    topic = re.sub(r"\b(last|past)\s+(week|month|year|quarter)\b.*$", "", topic, flags=re.I).strip()
    return topic if len(topic) >= 3 else ""


def _terms(topic: str) -> List[str]:
    return [w for w in re.split(r"[^a-z0-9]+", (topic or "").lower())
            if len(w) > 2 and w not in _STOP][:6]


def index_text(db, project_id: int, ref_kind: str, ref_id: int, text: str) -> bool:
    """Embed one message/memory for later recall. Best-effort — no provider → skipped (keyword
    search still finds it)."""
    if not (text or "").strip():
        return False
    try:
        from arvisx import embeddings as emb
        v = emb.embed_one(text)
        if not v:
            return False
        db.save_embedding(project_id, ref_kind, ref_id, emb.to_blob(v))
        return True
    except Exception:
        return False


def search(db, project_id: int, topic: str, k: int = 6) -> List[Dict[str, Any]]:
    """Semantic top-k over messages + memories; keyword fallback. Returns real rows with dates."""
    try:
        from arvisx import embeddings as emb
        qv = emb.embed_one(topic)
        if qv:
            rows = db.all_embeddings(project_id)
            scored = emb.top_k(qv, [(i, r["vec"]) for i, r in enumerate(rows)], k=k)
            refs = [(rows[i]["ref_kind"], rows[i]["ref_id"]) for i, _s in scored]
            hits = db.resolve_refs(project_id, refs)
            if hits:
                return hits
    except Exception:
        pass
    return db.keyword_search(project_id, _terms(topic), limit=k)


_RECALL_SYS = (
    "You help an interior-project team recall what was said. From the retrieved messages and "
    "memories below (each tagged with its date), answer the question and say WHEN it was said "
    "and by WHOM. Use ONLY these entries — never invent. If they don't cover it, say you "
    'couldn\'t find it. Be brief and concrete. Output JSON only: {"answer": "..."}.'
)


async def answer_recall(llm, hits: List[Dict[str, Any]], topic: str) -> str:
    if not hits:
        return f'I have nothing on record about "{topic}".'
    ctx = "\n".join(f"[{(h.get('ts') or '')[:10]}] {h.get('who') or '?'}"
                    f"{' (memory)' if h.get('kind') == 'memory' else ''}: {h.get('text', '')}"
                    for h in hits)
    if llm is not None:
        try:
            from arvisx.checklist_skills import _crisp, _looks_like_reasoning
            out = await llm.ask_json(
                messages=[{"role": "user", "content": f"{ctx}\n\nQUESTION: about {topic}"}],
                system_msgs=[{"role": "system", "content": _RECALL_SYS}], channel="chat")
            s = _crisp(str(out.get("answer", ""))).strip() if isinstance(out, dict) else ""
            if s and not _looks_like_reasoning(s):
                return s
        except Exception:
            pass
    lines = [f"• [{(h.get('ts') or '')[:10]}] {h.get('who') or '?'}: {h.get('text', '')[:110]}"
             for h in hits[:6]]
    return f'Here\'s what I have about "{topic}":\n' + "\n".join(lines)


# ── end-of-day: the day itself becomes a memory ───────────────────────────
_DAY_SYS = (
    "You write the end-of-day memory for ONE interior project, from that day's group chat and the "
    "actions the agent recorded. Capture what ACTUALLY happened: work done, commitments made "
    "(who, by when), blockers, approvals, and anything notable in the photos' descriptions. Use "
    "ONLY the material given — never invent. 3-6 short bullets, each starting '- '. "
    'Output JSON only: {"summary": "..."}.'
)


async def day_memory(llm, messages: List[Dict[str, Any]], activities: List[Dict[str, Any]],
                     media: List[Dict[str, Any]], date: str) -> str:
    """The day distilled into something worth keeping. Deterministic fallback if no LLM."""
    det = _deterministic_day(messages, activities, media, date)
    if llm is None:
        return det
    body = ("CHAT:\n" + "\n".join(f"{m.get('sender_name', '?')}: {m.get('text', '')[:160]}"
                                  for m in messages if (m.get("text") or "").strip())
            + "\n\nAGENT ACTIONS:\n" + "\n".join(f"{a['action']}: {a['detail'][:120]}" for a in activities)
            + "\n\nPHOTOS:\n" + "\n".join(f"{m.get('sender_name', '?')}: {m.get('caption', '')}"
                                          for m in media if m.get("caption")))
    try:
        from arvisx.checklist_skills import _crisp, _looks_like_reasoning
        out = await llm.ask_json(messages=[{"role": "user", "content": body}],
                                 system_msgs=[{"role": "system", "content": _DAY_SYS}], channel="chat")
        s = _crisp(str(out.get("summary", ""))).strip() if isinstance(out, dict) else ""
        if s and not _looks_like_reasoning(s) and len(s) <= 1200:
            return s
    except Exception:
        pass
    return det


def _deterministic_day(messages, activities, media, date: str) -> str:
    L = []
    done = [a for a in activities if a["action"] == "task_done"]
    made = [a for a in activities if a["action"] in ("commitment", "task_created")]
    blocked = [a for a in activities if a["action"] == "blocker"]
    appr = [a for a in activities if a["action"] == "approval"]
    if done:
        L.append("- Completed: " + "; ".join(a["detail"][:60] for a in done[:4]))
    if made:
        L.append("- Committed: " + "; ".join(a["detail"][:60] for a in made[:4]))
    if blocked:
        L.append("- Blocked: " + "; ".join(a["detail"][:60] for a in blocked[:3]))
    if appr:
        L.append("- Approvals: " + "; ".join(a["detail"][:60] for a in appr[:3]))
    caps = [m["caption"] for m in media if m.get("caption") and m["caption"] != "(no context given)"]
    if caps:
        L.append("- Photos: " + "; ".join(c[:50] for c in caps[:3]))
    if not L:
        L.append(f"- Quiet day — {len(messages)} messages, no recorded actions.")
    return "\n".join(L)
