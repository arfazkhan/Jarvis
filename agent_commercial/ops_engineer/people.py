"""
Who is who — the site's WhatsApp roster.

ARVIS_PEOPLE="Sara:+97455501111:fm, Ali:+97455501234:technician, Omar:+97455509999:owner"

Roles decide what ARVIS tells someone unprompted and what they may ask it to do:
  owner        asset owner / manager — outcomes and risks, not alarms
  fm           facilities manager / chief engineer — runs operations
  technician   on-site — answers checks, reports repairs
Anyone not on the roster is ignored: the number is the identity, there is no login.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

ROLES = ("owner", "fm", "technician")


def normalize_number(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


@dataclass(frozen=True)
class Person:
    name: str
    number: str
    role: str

    @property
    def first_name(self) -> str:
        return self.name.split()[0] if self.name else self.number


class People:
    def __init__(self, people: List[Person]):
        self._by_number: Dict[str, Person] = {p.number: p for p in people}

    @classmethod
    def parse(cls, raw: str) -> "People":
        out: List[Person] = []
        for part in (raw or "").split(","):
            bits = [b.strip() for b in part.split(":")]
            if len(bits) < 2:
                continue
            name, number = bits[0], normalize_number(bits[1])
            role = (bits[2].lower() if len(bits) > 2 and bits[2] else "fm")
            if not number:
                continue
            if role not in ROLES:
                raise ValueError(f"unknown role {role!r} for {name} (use one of {', '.join(ROLES)})")
            out.append(Person(name or number, number, role))
        return cls(out)

    @classmethod
    def from_env(cls) -> "People":
        return cls.parse(os.getenv("ARVIS_PEOPLE", ""))

    def get(self, number: str) -> Optional[Person]:
        return self._by_number.get(normalize_number(number))

    def by_role(self, *roles: str) -> List[Person]:
        return [p for p in self._by_number.values() if p.role in roles]

    def by_name(self, name: str) -> Optional[Person]:
        n = (name or "").strip().lower()
        exact = [p for p in self._by_number.values() if p.name.lower() == n or p.first_name.lower() == n]
        return exact[0] if len(exact) == 1 else None

    def technician_roster(self) -> Dict[str, str]:
        """{number: name} of technicians — the field-check roster."""
        return {p.number: p.name for p in self._by_number.values() if p.role == "technician"}

    def __len__(self) -> int:
        return len(self._by_number)
