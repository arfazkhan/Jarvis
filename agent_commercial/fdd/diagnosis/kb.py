"""
Per-rule diagnostic knowledge base — the NIST ZandrEA method (TN 2337),
reimplemented in Python (ZandrEA: US public domain + Apache-2.0).

For each FDD rule: a closed set of hypotheses (candidate causes, always
including H1 "spurious — the rule misfired") and evidence items (questions
whose answer discriminates between them). Each (evidence, hypothesis) link is
a small count table {no, yes, unevaluated} × {hypothesis false, true}.

Links come in two strengths:
  requires / excludes     hard (ZandrEA seeding): the wrong answer eliminates
                          the hypothesis — for physical facts
  supports / contradicts  soft: the answer shifts belief without eliminating

P(answer | hypothesis) is read from the "hypothesis true" column. Priors are
the hypothesis's repair track record on this rule — (verified + 1) /
(verified + failed + 2) — so causes that repairs actually fixed rise.
Learning (from closed-loop fix verification) increments the counts exactly as
ZandrEA does: true for the verified hypothesis, false for the others.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

ANSWERS = ("no", "yes", "unevaluated")

# Seed tables per link strength: answer → [hypothesis-false count, hypothesis-true count]
_SEEDS = {
    "requires":    {"no": [1, 0], "yes": [0, 1], "unevaluated": [1, 1]},
    "excludes":    {"no": [0, 1], "yes": [1, 0], "unevaluated": [1, 1]},
    "supports":    {"no": [3, 1], "yes": [1, 3], "unevaluated": [1, 1]},
    "contradicts": {"no": [1, 3], "yes": [3, 1], "unevaluated": [1, 1]},
    "learned":     {"no": [1, 1], "yes": [1, 1], "unevaluated": [1, 1]},
}
SPURIOUS = "H1"


@dataclass
class Hypothesis:
    id: str
    label: str


@dataclass
class EvidenceItem:
    id: str
    question: str
    links: Dict[str, str]                       # hypothesis id → link strength
    auto: Optional[Tuple] = None                # how ARVIS can answer it from data


@dataclass
class RuleKB:
    rule_id: str
    hypotheses: List[Hypothesis]
    evidence: List[EvidenceItem]
    counts: Dict[str, Dict[str, Dict[str, List[int]]]] = field(default_factory=dict)
    track: Dict[str, List[int]] = field(default_factory=dict)   # hyp → [verified, failed]

    @classmethod
    def seeded(cls, rule_id: str, hypotheses: List[Hypothesis], evidence: List[EvidenceItem]) -> "RuleKB":
        kb = cls(rule_id, hypotheses, evidence)
        for ev in evidence:
            kb.counts[ev.id] = {h: {a: list(_SEEDS[s][a]) for a in ANSWERS} for h, s in ev.links.items()}
        kb.track = {h.id: [0, 0] for h in hypotheses}
        return kb

    # ── probabilities ────────────────────────────────────────────────────
    def prior(self) -> Dict[str, float]:
        raw = {h.id: (self.track.get(h.id, [0, 0])[0] + 1.0)
                     / (sum(self.track.get(h.id, [0, 0])) + 2.0) for h in self.hypotheses}
        z = sum(raw.values())
        return {k: v / z for k, v in raw.items()}

    def likelihood(self, ev_id: str, hyp_id: str, answer: str) -> Optional[float]:
        """P(answer | hypothesis true); None for an unevaluated answer.

        A hypothesis the evidence is not linked to gets the uninformative value
        of a flat node (not 1.0 — skipping it would rank unrelated hypotheses
        above the ones a 'requires'/'supports' answer points to)."""
        if answer == "unevaluated":
            return None
        node = self.counts.get(ev_id, {}).get(hyp_id) or _SEEDS["learned"]
        total = sum(node[a][1] for a in ANSWERS)
        return node[answer][1] / total if total else None

    def hypothesis(self, hyp_id: str) -> Optional[Hypothesis]:
        return next((h for h in self.hypotheses if h.id == hyp_id), None)

    def evidence_item(self, ev_id: str) -> Optional[EvidenceItem]:
        return next((e for e in self.evidence if e.id == ev_id), None)

    def match_hypothesis(self, text: Optional[str]) -> Optional[str]:
        """Resolve 'H3', 'FC14:H3' or a label fragment to a hypothesis id."""
        if not text:
            return None
        t = str(text).strip()
        tid = t.split(":")[-1].upper()
        if self.hypothesis(tid):
            return tid
        low = t.lower()
        hits = [h.id for h in self.hypotheses if low in h.label.lower() or h.label.lower() in low]
        return hits[0] if len(hits) == 1 else None

    # ── learning (ZandrEA count increments) ──────────────────────────────
    def learn(self, answers: Dict[str, str], hyp_id: str, verified: bool) -> None:
        if hyp_id not in self.track:
            return
        self.track[hyp_id][0 if verified else 1] += 1
        if not verified:
            return
        for ev_id, ans in answers.items():
            if ans not in ANSWERS or ev_id not in self.counts:
                continue
            nodes = self.counts[ev_id]
            if hyp_id not in nodes:        # a new association discovered by a verified fix
                nodes[hyp_id] = {a: list(_SEEDS["learned"][a]) for a in ANSWERS}
            for h, node in nodes.items():
                node[ans][1 if h == hyp_id else 0] += 1

    # ── persistence ──────────────────────────────────────────────────────
    def to_json(self) -> str:
        return json.dumps({
            "rule_id": self.rule_id,
            "hypotheses": [h.__dict__ for h in self.hypotheses],
            "evidence": [{"id": e.id, "question": e.question, "links": e.links,
                          "auto": list(e.auto) if e.auto else None} for e in self.evidence],
            "counts": self.counts, "track": self.track})

    @classmethod
    def from_json(cls, s: str) -> "RuleKB":
        d = json.loads(s)
        return cls(d["rule_id"], [Hypothesis(**h) for h in d["hypotheses"]],
                   [EvidenceItem(e["id"], e["question"], e["links"],
                                 tuple(e["auto"]) if e.get("auto") else None) for e in d["evidence"]],
                   d.get("counts", {}), d.get("track", {}))

    def summary(self) -> Dict[str, Any]:
        return {"rule_id": self.rule_id,
                "hypotheses": [{"id": h.id, "label": h.label, "verified": self.track[h.id][0],
                                "failed": self.track[h.id][1]} for h in self.hypotheses],
                "evidence": [{"id": e.id, "question": e.question, "links": e.links,
                              "auto": bool(e.auto)} for e in self.evidence]}
