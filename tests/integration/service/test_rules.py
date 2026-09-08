"""T-SVC-063/064: the user's own rules for the agent."""

from __future__ import annotations

import pytest

from victus.application.errors import NotFound, ValidationFailed
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import rules as uc
from victus.application.use_cases import settings as settings_uc
from victus.application.use_cases._base import UowFactory

BASE = {
    "goal": {"weight_kg": 80, "date": "2027-01-31"},
    "kcal_per_kg": 7716.17,
    "calorie_corridor": {"min": 1400, "max": 2000, "asymmetric": True},
    "target_bands": [
        {
            "name": "Rest day",
            "training_type": "rest",
            "valid_from": "2026-08-18",
            "protein": {"min": 105, "opt_min": 150, "opt_max": 185, "target": 165, "max": 200},
            "carbs": {"min": 120, "opt_min": 155, "opt_max": 200, "target": 180, "max": 230},
            "fat": {"min": 45, "opt_min": 55, "opt_max": 70, "target": 58, "max": 75},
            "fiber": {"min": 25, "opt_min": 32, "opt_max": 38, "target": 35, "max": 50},
            "salt": {"min": 4, "opt_min": 6, "opt_max": 8, "target": 8, "max": 15},
        }
    ],
}


def test_rules_are_added_replaced_and_removed(
    factory: UowFactory, alice: TenantContext, bob: TenantContext
) -> None:
    settings_uc.PutSettings(factory, alice).execute(dict(BASE))

    first = uc.UpsertRule(factory, alice).execute(
        uc.RuleInput(when="bread rolls from the bakery", then="use the bakery's own site")
    )
    assert first.name == "bread-rolls-from-the-bakery" and first.scope == "all"

    uc.UpsertRule(factory, alice).execute(
        uc.RuleInput(
            when="packaged food", then="check the open database", scope="products", priority=10
        )
    )
    rows = uc.ListRules(factory, alice).execute()
    assert [r.when for r in rows] == ["packaged food", "bread rolls from the bakery"]  # priority
    assert [r.when for r in uc.ListRules(factory, alice).execute(scope="days")] == [
        "bread rolls from the bakery"
    ]
    assert uc.ListRules(factory, bob).execute() == []

    # same name replaces instead of duplicating
    again = uc.UpsertRule(factory, alice).execute(
        uc.RuleInput(when="bread rolls from the bakery", then="ask me first", enabled=False)
    )
    assert again.then == "ask me first"
    rows = uc.ListRules(factory, alice).execute()
    assert len(rows) == 2
    assert [r.when for r in uc.ListRules(factory, alice).execute(enabled_only=True)] == [
        "packaged food"
    ]

    uc.DeleteRule(factory, alice).execute("bread rolls from the bakery")
    assert [r.when for r in uc.ListRules(factory, alice).execute()] == ["packaged food"]
    with pytest.raises(NotFound):
        uc.DeleteRule(factory, alice).execute("bread rolls from the bakery")

    # every change is a settings version, so the history stays readable
    assert len(settings_uc.SettingsVersions(factory, alice).execute()) == 5


def test_rules_are_validated_and_rendered_for_the_agent(
    factory: UowFactory, alice: TenantContext
) -> None:
    settings_uc.PutSettings(factory, alice).execute(dict(BASE))
    with pytest.raises(ValidationFailed):
        uc.UpsertRule(factory, alice).execute(uc.RuleInput(when="  ", then="x"))
    with pytest.raises(ValidationFailed):
        uc.UpsertRule(factory, alice).execute(uc.RuleInput(when="x", then="y", scope="nonsense"))

    assert uc.rules_markdown([]) == ""
    uc.UpsertRule(factory, alice).execute(uc.RuleInput(when="ice cream", then="80 g per scoop"))
    text = uc.rules_markdown(uc.ListRules(factory, alice).execute())
    assert "The user's own rules" in text and "**ice cream** → 80 g per scoop" in text
