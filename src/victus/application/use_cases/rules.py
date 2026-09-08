"""Sourcing rules: your own instructions for the agent (SPEC R61).

A rule says *when* something applies and *what to do then*, in your words:
"bread rolls from the local bakery → look the values up on the bakery's own
site, they beat any database". Rules live in the versioned tenant settings, so
every change keeps a history, and they are handed to the agent with each
drafting session.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from victus.application import dto
from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.tenant_context import SCOPE_READ, SCOPE_WRITE
from victus.application.use_cases._base import UseCase
from victus.application.use_cases.settings import sync_target_bands, validate_settings

SCOPES = ("products", "days", "reports", "all")
MAX_RULES = 100


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:60]


@dataclass(frozen=True, slots=True)
class RuleInput:
    when: str
    then: str
    name: str | None = None
    scope: str = "all"
    enabled: bool = True
    priority: int = 100


def rule_view(raw: dict[str, Any]) -> dto.RuleView:
    return dto.RuleView(
        name=str(raw.get("name", "")),
        when=str(raw.get("when", "")),
        then=str(raw.get("then", "")),
        scope=str(raw.get("scope", "all")),
        enabled=raw.get("enabled", True) is not False,
        priority=int(raw.get("priority", 100)),
    )


def rules_of(
    data: dict[str, Any], *, scope: str | None = None, enabled_only: bool = False
) -> list[dto.RuleView]:
    """Rules from a settings document, most important first."""
    raw = data.get("rules")
    rows = [rule_view(r) for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []
    if enabled_only:
        rows = [r for r in rows if r.enabled]
    if scope:
        rows = [r for r in rows if r.scope in (scope, "all")]
    return sorted(rows, key=lambda r: (r.priority, r.name))


def rules_markdown(rules: list[dto.RuleView]) -> str:
    """The rules as the agent sees them; empty string when there are none."""
    if not rules:
        return ""
    lines = [
        "## The user's own rules",
        "",
        "Follow these before falling back to your own judgement.",
    ]
    lines += [f"- **{r.when}** → {r.then}" for r in rules]
    return "\n".join(lines)


def _document(uow: UnitOfWork) -> dict[str, Any]:
    current = uow.settings.current()
    if current is None:
        raise NotFound("no tenant settings yet — save the settings once before adding rules")
    return dict(current.data)


class ListRules(UseCase):
    def execute(
        self, *, scope: str | None = None, enabled_only: bool = False
    ) -> list[dto.RuleView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            current = uow.settings.current()
            return rules_of(
                dict(current.data) if current else {}, scope=scope, enabled_only=enabled_only
            )


class UpsertRule(UseCase):
    """Add a rule, or replace the one with the same name."""

    def execute(self, rule: RuleInput) -> dto.RuleView:
        self.ctx.require(SCOPE_WRITE)
        when, then = rule.when.strip(), rule.then.strip()
        if not when or not then:
            raise ValidationFailed("a rule needs both a 'when' and a 'then'")
        if rule.scope not in SCOPES:
            raise ValidationFailed(f"scope must be one of {', '.join(SCOPES)}")
        name = _slug(rule.name or when)
        if not name:
            raise ValidationFailed("the rule name must contain letters or digits")
        with self._uow() as uow:
            data = _document(uow)
            rules = [r for r in (data.get("rules") or []) if isinstance(r, dict)]
            if len(rules) >= MAX_RULES and all(r.get("name") != name for r in rules):
                raise Conflict(f"at most {MAX_RULES} rules")
            entry = {
                "name": name,
                "when": when,
                "then": then,
                "scope": rule.scope,
                "enabled": rule.enabled,
                "priority": rule.priority,
            }
            rules = [r for r in rules if r.get("name") != name] + [entry]
            data["rules"] = rules
            validate_settings(data)
            row = uow.settings.add_version(data, date.today(), self.ctx.actor_id)
            sync_target_bands(uow, data)
            uow.audit.record("settings.rule.upsert", "tenant_settings", str(row.version), entry)
            uow.commit()
            return rule_view(entry)


class DeleteRule(UseCase):
    def execute(self, name: str) -> None:
        self.ctx.require(SCOPE_WRITE)
        key = _slug(name)
        with self._uow() as uow:
            data = _document(uow)
            rules = [r for r in (data.get("rules") or []) if isinstance(r, dict)]
            kept = [r for r in rules if r.get("name") != key]
            if len(kept) == len(rules):
                raise NotFound(f"no rule named {name!r}")
            data["rules"] = kept
            validate_settings(data)
            row = uow.settings.add_version(data, date.today(), self.ctx.actor_id)
            uow.audit.record(
                "settings.rule.delete", "tenant_settings", str(row.version), {"name": key}
            )
            uow.commit()
