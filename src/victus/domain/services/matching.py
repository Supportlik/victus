"""Name matching between free-text line items and the consumable catalogue.

Three tiers, ported from the source vault's importer with its two documented traps:

1. **Exact** on the normalised name *including* parentheses. The parentheses carry
   the distinguishing information ("Kartoffel (roh)" vs "(gekocht)", "TK" vs "frisch");
   dropping them once produced three days computed with the wrong fibre value.
2. **Exact without parentheses**, only when the short form is unique in the index
   ("Skyr Natur (Arla)" ↔ "Arla Skyr Natur"). Ambiguous short forms are skipped.
3. **Fuzzy**: substring coverage or token Jaccard, threshold 0.62 for products and
   0.75 for recipes. Pure substring matching once let "Leinsamen (geschrotet)" hit the
   recipe "Skyr-Beeren-Leinsamen"; the coverage rule prevents that.

Scores double as confidence values for the agent and the review list.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from victus.domain.services.quantity_parser import clean_text
from victus.domain.values import ConsumableKind, MatchCandidate

THRESHOLD: dict[ConsumableKind, float] = {
    ConsumableKind.PRODUCT: 0.62,
    ConsumableKind.RECIPE_BATCH: 0.75,
    ConsumableKind.AD_HOC: 0.9,
}
MIN_KEY_LENGTH = 5

# "(…)" up to the first closing bracket, as the lazy ".*?" did — but the class excludes the
# opening bracket as well, so "((((((…" in a name a person typed fails at once instead of
# scanning to the end of the string once per position.
_PARENS = re.compile(r"\([^()]*\)")


def normalize(name: str | None) -> str:
    """Lower-case ASCII form for comparison; parentheses content is kept."""
    s = clean_text(name).lower()
    s = s.replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def short_form(name: str | None) -> str:
    """Normalised name with every parenthesised part removed."""
    return normalize(_PARENS.sub(" ", clean_text(name)))


def coverage(a: str, b: str) -> float:
    """Similarity in [0, 1]: length ratio for substrings, token Jaccard otherwise."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b))
    ta, tb = set(a.split()), set(b.split())
    if not (ta & tb):
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass(frozen=True, slots=True)
class _Entry:
    consumable_id: int
    kind: ConsumableKind
    name: str
    full: str
    short: str


class ConsumableIndex:
    """Index over ``(id, kind, name)`` triples with three-tier lookup."""

    def __init__(self, entries: Iterable[tuple[int, ConsumableKind | str, str]]) -> None:
        self._entries: list[_Entry] = []
        self._full: dict[str, _Entry] = {}
        short_groups: dict[str, list[_Entry]] = {}
        for cid, kind, name in entries:
            e = _Entry(cid, ConsumableKind(kind), name, normalize(name), short_form(name))
            self._entries.append(e)
            self._full.setdefault(e.full, e)
            if e.short:
                short_groups.setdefault(e.short, []).append(e)
        self._short_unique: dict[str, _Entry] = {
            k: v[0] for k, v in short_groups.items() if len(v) == 1
        }

    def __len__(self) -> int:
        return len(self._entries)

    def find(self, text: str | None, limit: int = 3) -> list[MatchCandidate]:
        """Candidates ordered by tier then score; empty when nothing qualifies."""
        full = normalize(text)
        if not full:
            return []
        short = short_form(text)
        out: list[MatchCandidate] = []
        seen: set[int] = set()

        hit = self._full.get(full)
        if hit:
            out.append(MatchCandidate(hit.consumable_id, hit.name, hit.kind, 1, 1.0))
            seen.add(hit.consumable_id)

        hit = self._short_unique.get(short)
        if hit and hit.consumable_id not in seen:
            out.append(MatchCandidate(hit.consumable_id, hit.name, hit.kind, 2, 0.95))
            seen.add(hit.consumable_id)

        fuzzy: list[MatchCandidate] = []
        for e in self._entries:
            if e.consumable_id in seen or len(e.full) < MIN_KEY_LENGTH:
                continue
            score = max(coverage(full, e.full), coverage(short, e.short) if e.short else 0.0)
            if score >= THRESHOLD[e.kind]:
                fuzzy.append(MatchCandidate(e.consumable_id, e.name, e.kind, 3, round(score, 4)))
        fuzzy.sort(key=lambda c: (-c.score, c.name))
        out.extend(fuzzy)
        return out[:limit]

    def best(self, text: str | None) -> MatchCandidate | None:
        """Single best candidate. Recipe batches win over products when both qualify,
        mirroring the source importer (a recipe name is long and specific)."""
        candidates = self.find(text, limit=10)
        if not candidates:
            return None
        recipes = [c for c in candidates if c.kind is ConsumableKind.RECIPE_BATCH]
        if recipes and (
            recipes[0].tier < 3 or recipes[0].score >= THRESHOLD[ConsumableKind.RECIPE_BATCH]
        ):
            return recipes[0]
        return candidates[0]
