"""
Naive-Bayes diagnosis over a RuleKB (ZandrEA method).

Hypotheses are exhaustive and mutually exclusive for one failed rule. Each
answered evidence item multiplies in P(answer | hypothesis); a zero eliminates
the hypothesis. If every hypothesis is eliminated the knowledge base is "bust"
(the true cause is not modelled) — reported, never papered over.

ARVIS change: the next question is the one with the highest expected
information gain, not ZandrEA's fixed queue order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from agent_commercial.fdd.diagnosis.kb import RuleKB


@dataclass
class Diagnosis:
    posterior: List[Dict]                      # [{id, label, p}] ranked
    eliminated: List[str] = field(default_factory=list)
    kb_bust: bool = False
    spent: bool = False                        # every question answered, still not certain
    next_question: Optional[Dict] = None

    @property
    def top(self) -> Optional[Dict]:
        return self.posterior[0] if self.posterior else None

    def to_dict(self) -> Dict:
        return {"posterior": self.posterior, "eliminated": self.eliminated, "kb_bust": self.kb_bust,
                "spent": self.spent, "next_question": self.next_question}


def _posterior(kb: RuleKB, answers: Dict[str, str]) -> (Dict[str, float], List[str], bool):
    prior = kb.prior()
    scores = dict(prior)
    for ev_id, ans in answers.items():
        if ans not in ("yes", "no"):
            continue
        for h in list(scores):
            lk = kb.likelihood(ev_id, h, ans)
            if lk is not None:
                scores[h] *= lk
    eliminated = [h for h, s in scores.items() if s <= 0.0]
    z = sum(scores.values())
    if z <= 0.0:
        return prior, eliminated, True           # KB bust: nothing modelled fits
    return {h: s / z for h, s in scores.items()}, eliminated, False


def _entropy(p: Dict[str, float]) -> float:
    return -sum(v * math.log(v) for v in p.values() if v > 0)


def _info_gain(kb: RuleKB, answers: Dict[str, str], ev_id: str, current: Dict[str, float]) -> float:
    gain, h0 = 0.0, _entropy(current)
    p_ans = {}
    for ans in ("yes", "no"):
        s = 0.0
        for h, ph in current.items():
            lk = kb.likelihood(ev_id, h, ans)
            s += ph * (lk if lk is not None else 0.0)
        p_ans[ans] = s
    z = sum(p_ans.values()) or 1.0
    for ans in ("yes", "no"):
        post, _, bust = _posterior(kb, {**answers, ev_id: ans})
        if not bust:
            gain += (p_ans[ans] / z) * (h0 - _entropy(post))
    return gain


def diagnose(kb: RuleKB, answers: Dict[str, str]) -> Diagnosis:
    post, eliminated, bust = _posterior(kb, answers)
    ranked = sorted(({"id": h.id, "label": h.label, "p": round(post.get(h.id, 0.0), 4)}
                     for h in kb.hypotheses), key=lambda x: -x["p"])
    open_items = [e for e in kb.evidence if answers.get(e.id) not in ("yes", "no")]
    next_q = None
    if not bust and open_items and ranked and ranked[0]["p"] < 0.999:
        best = max(open_items, key=lambda e: _info_gain(kb, answers, e.id, post))
        if _info_gain(kb, answers, best.id, post) > 1e-9:
            next_q = {"evidence_id": best.id, "question": best.question}
    spent = (not bust and not open_items and bool(ranked) and ranked[0]["p"] < 0.999)
    return Diagnosis(ranked, eliminated, bust, spent, next_q)
