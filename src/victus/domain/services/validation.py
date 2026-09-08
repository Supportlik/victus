"""Day consistency check (predecessor ``pruefe_logs.py``).

Four finding kinds:

0. control flags missing (``reliable`` / ``status`` is ``None``) — the day counts nowhere
1. drift between the declared source macros and the balance table
2. balance versus the sum of the meal totals — only assessable when *every* meal has
   a total row; otherwise a ``not_assessable`` info finding, never an error
3. gaps: macros missing on a countable day; salt-only gaps before the salt tracking
   start are ``expected_gap``

A check must distinguish "error found" from "cannot judge" — otherwise people
learn to ignore it.
"""

from __future__ import annotations

from victus.domain.model.checks import DayForCheck, Tolerances
from victus.domain.services.nutrients import sum_macros
from victus.domain.values import MACRO_KEYS, DayStatus, Finding, Macros

ERROR_KINDS = {0, 1, 2}
INFO_CODES = {"not_assessable", "expected_gap"}


def _exceeds(key: str, a: float, b: float, tol: Tolerances) -> bool:
    if key == "kcal":
        return abs(a - b) > max(tol.kcal_abs, abs(b) * tol.kcal_rel)
    return abs(a - b) > tol.for_macro(key)


def is_error(finding: Finding) -> bool:
    return finding.kind in ERROR_KINDS and finding.code not in INFO_CODES


def is_countable(day: DayForCheck) -> bool:
    return day.reliable is True and day.status is DayStatus.CLOSED


def check_day(day: DayForCheck, tol: Tolerances | None = None) -> list[Finding]:
    tol = tol or Tolerances()
    findings: list[Finding] = []

    # 0 — control flags
    missing = [n for n, v in (("reliable", day.reliable), ("status", day.status)) if v is None]
    if missing:
        findings.append(
            Finding(0, "flags_missing", f"missing control flags: {', '.join(missing)}", day.day)
        )

    # 1 — source vs. balance drift (only where both declare the macro)
    if day.source is not None and day.balance is not None:
        for key in MACRO_KEYS:
            a, b = getattr(day.source, key), getattr(day.balance, key)
            if a is None or b is None:
                continue
            if _exceeds(key, a, b, tol):
                findings.append(
                    Finding(
                        1,
                        "source_balance_drift",
                        f"{key}: source {a} vs balance {b}",
                        day.day,
                        {"macro": key, "source": a, "balance": b},
                    )
                )

    # 2 — balance vs. meal totals (kcal, like the predecessor), or vs. item sum
    reference = day.balance if day.balance is not None else day.source
    if reference is not None and reference.kcal is not None:
        if day.meal_totals:
            if any(t is None for t in day.meal_totals):
                findings.append(
                    Finding(
                        2,
                        "not_assessable",
                        "meal table without total row; balance cannot be assessed",
                        day.day,
                        {
                            "meals": len(day.meal_totals),
                            "with_total": sum(1 for t in day.meal_totals if t),
                        },
                    )
                )
            else:
                total = sum_macros([t for t in day.meal_totals if t is not None])
                if total.kcal is not None and _exceeds("kcal", total.kcal, reference.kcal, tol):
                    findings.append(
                        Finding(
                            2,
                            "balance_mismatch",
                            f"meal totals {total.kcal:.0f} kcal vs balance "
                            f"{reference.kcal:.0f} kcal",
                            day.day,
                            {
                                "meal_totals": total.kcal,
                                "balance": reference.kcal,
                                "diff": total.kcal - reference.kcal,
                            },
                        )
                    )
        elif (
            day.item_sum is not None
            and day.item_sum.kcal is not None
            and _exceeds("kcal", day.item_sum.kcal, reference.kcal, tol)
        ):
            findings.append(
                Finding(
                    2,
                    "balance_mismatch",
                    f"items {day.item_sum.kcal:.0f} kcal vs balance {reference.kcal:.0f} kcal",
                    day.day,
                    {
                        "items": day.item_sum.kcal,
                        "balance": reference.kcal,
                        "diff": day.item_sum.kcal - reference.kcal,
                    },
                )
            )

    # 3 — gaps on countable days
    if is_countable(day):
        declared: Macros = day.source or day.balance or Macros()
        gaps = [k for k in MACRO_KEYS if getattr(declared, k) is None]
        if gaps == ["salt"] and (
            day.salt_tracking_start is None or day.day < day.salt_tracking_start
        ):
            findings.append(
                Finding(3, "expected_gap", "salt not tracked yet", day.day, {"macros": "salt"})
            )
        elif gaps:
            findings.append(
                Finding(
                    3, "gap", f"missing: {', '.join(gaps)}", day.day, {"macros": ",".join(gaps)}
                )
            )

    return findings


def has_errors(findings: list[Finding]) -> bool:
    return any(is_error(f) for f in findings)
