"""Domain pack (DESIGN A6): the business vocabulary of one sandbox, kept out of the core.
Stored in `sandbox.domain_pack`, authored in `sandboxes/<sandbox>/domain.yaml`."""
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from cortex_leads.core.errors import CortexError
from cortex_leads.core.vocabulary import CORE_FACT_KINDS
from cortex_leads.privacy.redact import _fold

OUTCOME_STATUSES = {"booked", "won", "lost", "cancelled"}  # deal.status values


class DomainPackError(CortexError):
    """domain.yaml or sandbox.domain_pack is malformed."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Intent(_Strict):
    label: str
    keywords: list[str]


class DomainPack(_Strict):
    intents: dict[str, Intent] = {}
    reason_codes: list[str] | dict[str, str] = []  # list, or {code: label}
    fact_kinds: list[str] = []
    decision_maker_roles: list[str] = []
    outcome_keywords: dict[str, list[str]] = {}
    priority_intents: list[str] = []  # ranked first when the daily cap forces a choice

    @field_validator("outcome_keywords")
    @classmethod
    def _statuses(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        if bad := set(v) - OUTCOME_STATUSES:
            raise ValueError(f"outcome_keywords keys must be in {sorted(OUTCOME_STATUSES)}: {sorted(bad)}")
        return v

    @property
    def all_fact_kinds(self) -> set[str]:
        return CORE_FACT_KINDS | set(self.fact_kinds)

    def reason_label(self, code: str) -> str:
        return self.reason_codes.get(code, code) if isinstance(self.reason_codes, dict) else code

    def match_intent(self, text: str) -> str | None:
        """First intent (declaration order) with a keyword in `text`: whole words, no diacritics,
        case-insensitive. None when nothing matches or the pack declares no intents."""
        folded = _fold(text)
        for name, intent in self.intents.items():
            if any(_word(k).search(folded) for k in intent.keywords if k.strip()):
                return name
        return None

    def match_outcome(self, text: str) -> str | None:
        folded = _fold(text)
        for status, words in self.outcome_keywords.items():
            if any(_word(k).search(folded) for k in words if k.strip()):
                return status
        return None


def _word(keyword: str) -> re.Pattern[str]:
    words = _fold(keyword).split()
    return re.compile(r"(?<!\w)" + r"\s+".join(re.escape(w) for w in words) + r"(?!\w)")


def parse_pack(data: Any) -> DomainPack:
    try:
        return DomainPack.model_validate(data if data is not None else {})
    except ValidationError as e:
        raise DomainPackError(f"invalid domain pack: {e}") from e


def load_pack(sandbox: Any) -> DomainPack:
    """From `sandbox.domain_pack`. `{}` (never synced) is a valid, empty pack."""
    return parse_pack(sandbox.domain_pack)


def load_pack_file(path: Path) -> DomainPack:
    from cortex_leads.skills.loader import load_yaml  # lazy: loader imports this module

    if not path.is_file():
        raise DomainPackError(f"domain pack not found: {path}")
    return parse_pack(load_yaml(path.read_text(encoding="utf-8")))
