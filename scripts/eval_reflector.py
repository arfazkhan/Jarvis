"""Evaluate the memory reflector (arvis_core/decision/reflector.py): rule vs. Kev.

Real empty memory searches are not in the logs (they record that a tool ran, not its
query or result), so this harness REPLAYS the real investigation queries stored in
investigation_plans through the real query_skillbook tool, against a copy of the DB
(never the live file), and keeps every search that comes back empty, with its
`retrieval` diagnostics.

  extract   replay queries → cases JSONL (one empty search per line, label = null)
  score     compare gate/rule/kev decisions with your labels

Labelling: set "label" on each case to "retry" (a reworded search should find relevant
past experience — one of the near misses is about THIS equipment and THIS problem) or
"accept" (nothing relevant exists). Only labelled cases are scored.

  python scripts/eval_reflector.py extract --out reports/reflector_cases.jsonl
  python scripts/eval_reflector.py score --cases reports/reflector_cases.jsonl [--kev]

--kev needs ARVIS_DECISION_URL pointing at a running Kev server; without it the Kev
column reports how many cases it could not answer.
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LIVE_DB = ROOT / "agent_commercial" / "data" / "arvis_bms.db"
_EQ = re.compile(r"\b(?:CH|AHU|VAV|FCU|MTR|CHILLER|PUMP|CT)[-_\s]?\d+\b", re.I)


def _queries(db: Path, extra: Path = None) -> List[str]:
    """Every real query this building has seen: investigations, operator chat and
    turns, and alarms phrased the way the autonomous investigator phrases them."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    sources = [
        "SELECT query FROM investigation_plans",
        "SELECT content FROM chat_messages WHERE role = 'user'",
        "SELECT content FROM conversation_turns WHERE role = 'user' AND is_summary = 0",
        "SELECT 'AUTONOMOUS INVESTIGATION: ' || UPPER(severity) || ' alarm on ' || equipment_id"
        " || '. Description: ' || message || '. Diagnose root cause.' FROM alarms",
    ]
    found = set()
    try:
        for sql in sources:
            try:
                found |= {(r[0] or "").strip() for r in conn.execute(sql).fetchall()}
            except sqlite3.OperationalError:
                pass   # table absent in this DB
    finally:
        conn.close()
    if extra:
        found |= {l.strip() for l in extra.read_text(encoding="utf-8").splitlines()}
    return sorted(q for q in found if q)


def _offline() -> None:
    """The replay must cost nothing and leak nothing: block every non-local host
    (the skillbook's reranker otherwise falls back to Bedrock), and load the
    embedding model from the local HF cache only."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from agent_commercial.egress_policy import EgressPolicy, install
    install(EgressPolicy.from_allow_list(""))
    try:
        # Loading by repo id in offline mode fails on Windows in some transformers
        # versions even with a complete cache; loading the snapshot path works.
        from huggingface_hub import snapshot_download
        from sentence_transformers import SentenceTransformer
        from agent_commercial.ml.building_embeddings import SemanticSkillMatcher
        name = SemanticSkillMatcher.DEFAULT_MODEL
        path = snapshot_download(f"sentence-transformers/{name}", local_files_only=True)
        if not hasattr(sys, "_arvis_st_model_cache"):
            sys._arvis_st_model_cache = {}
        sys._arvis_st_model_cache[name] = SentenceTransformer(path)
    except Exception as e:
        raise SystemExit(f"Embedding model not available offline ({e}). Without it every case is "
                         "'semantic unavailable' and the evaluation means nothing.")


async def _extract(out: Path, limit: int, extra: Path = None) -> None:
    _offline()
    tmp = Path(tempfile.mkdtemp(prefix="arvis_reflector_eval_"))
    copy = tmp / "arvis_bms.db"
    shutil.copy2(LIVE_DB, copy)          # never touch the live DB
    os.environ["ARVIS_DB_PATH"] = str(copy)

    from agent_commercial.tools.handlers.sovereign import SovereignHandlerMixin
    from arvis_core.decision.reflector import decide_reflection

    class _Tool(SovereignHandlerMixin):
        memory_orchestrator = None
        knowledge_base = None
        tracker = None

    tool = _Tool()
    queries = _queries(copy, extra)
    queries = queries[:limit] if limit else queries
    cases, searched = [], 0
    for q in queries:
        # Search the way agents do: the whole query, and scoped to each unit it names.
        variants = [{"query": q}] + [{"query": q, "equipment_id": e.upper()} for e in sorted(set(_EQ.findall(q)))]
        for args in variants:
            searched += 1
            res = await tool._handle_query_skillbook(dict(args))
            if not isinstance(res, dict) or res.get("skills") != []:
                continue
            diag = res.get("retrieval")
            rule = await decide_reflection(diag, query=q, judge="rule")
            cases.append({
                "id": f"c{len(cases):04d}", "args": args, "retrieval": diag,
                "rule": rule.to_dict() if rule else None, "label": None,
            })
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, default=str) + "\n")
    shutil.rmtree(tmp, ignore_errors=True)
    reasons: Dict[str, int] = {}
    for c in cases:
        r = (c["retrieval"] or {}).get("empty_reason", "no_diagnostics")
        reasons[r] = reasons.get(r, 0) + 1
    print(f"{len(queries)} queries, {searched} searches, {len(cases)} empty → {out}")
    print("empty_reason:", json.dumps(reasons, sort_keys=True))


def _metrics(pairs: List[tuple]) -> Dict[str, Any]:
    """pairs of (predicted_retry: bool|None, label_retry: bool). None = abstained."""
    answered = [(p, y) for p, y in pairs if p is not None]
    tp = sum(1 for p, y in answered if p and y)
    fp = sum(1 for p, y in answered if p and not y)
    fn = sum(1 for p, y in answered if not p and y)
    tn = sum(1 for p, y in answered if not p and not y)
    n = len(answered)
    return {
        "n": n, "abstained": len(pairs) - n,
        "accuracy": round((tp + tn) / n, 3) if n else None,
        "wasted_retries(fp)": fp, "lost_experience(fn)": fn,
        "retry_precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "retry_recall": round(tp / (tp + fn), 3) if tp + fn else None,
    }


async def _score(cases_path: Path, use_kev: bool) -> None:
    from arvis_core.decision.reflector import decide_reflection, gate, kev_judge

    cases = [json.loads(l) for l in cases_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    labelled = [c for c in cases if c.get("label") in ("retry", "accept")]
    if not labelled:
        print(f"No labelled cases in {cases_path} ({len(cases)} total). Set \"label\" to retry/accept first.")
        return

    rows = {"rule (gate+rule)": [], "kev (gate+kev)": [], "ambiguous only: rule": [], "ambiguous only: kev": []}
    probs = []
    for c in labelled:
        diag, y = c.get("retrieval"), c["label"] == "retry"
        q = c["args"].get("query", "")
        r = await decide_reflection(diag, query=q, judge="rule")
        rows["rule (gate+rule)"].append((r.retry if r else False, y))
        ambiguous = isinstance(diag, dict) and gate(diag) is None
        if ambiguous:
            rows["ambiguous only: rule"].append((r.retry if r else False, y))
        if use_kev:
            if ambiguous:
                p = await kev_judge(diag, q)
                kp = None if p is None else p >= float(os.getenv("ARVIS_REFLECTOR_KEV_THRESHOLD", "0.5"))
                rows["ambiguous only: kev"].append((kp, y))
                rows["kev (gate+kev)"].append((kp, y))
                if p is not None:
                    probs.append((p, y))
            else:
                g = gate(diag) if isinstance(diag, dict) else None
                rows["kev (gate+kev)"].append((g.retry if g else False, y))

    print(f"{len(labelled)} labelled of {len(cases)} cases")
    for name, pairs in rows.items():
        if pairs:
            print(f"  {name:24s} {json.dumps(_metrics(pairs))}")
    if probs:
        brier = sum((p - (1.0 if y else 0.0)) ** 2 for p, y in probs) / len(probs)
        print(f"  kev brier on ambiguous: {brier:.3f} (n={len(probs)})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--out", type=Path, default=ROOT / "reports" / "reflector_cases.jsonl")
    e.add_argument("--limit", type=int, default=0)
    e.add_argument("--queries", type=Path, default=None, help="extra real queries, one per line")
    s = sub.add_parser("score")
    s.add_argument("--cases", type=Path, default=ROOT / "reports" / "reflector_cases.jsonl")
    s.add_argument("--kev", action="store_true")
    a = ap.parse_args()
    if a.cmd == "extract":
        asyncio.run(_extract(a.out, a.limit, a.queries))
    else:
        asyncio.run(_score(a.cases, a.kev))


if __name__ == "__main__":
    main()
