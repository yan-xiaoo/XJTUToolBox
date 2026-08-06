"""Shared score statistics used by both the score page and Wenzhou context."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class ScoreStatistics:
    total_credit: float
    weighted_gpa: float | None
    weighted_average: float | None
    incomplete_count: int
    course_count: int


def calculate_score_statistics(scores: Iterable[Mapping]) -> ScoreStatistics | None:
    """Calculate the score page's credit-weighted summary once, consistently."""

    rows = [one for one in scores if isinstance(one, Mapping)]
    total_credit = 0.0
    gpa_total = 0.0
    gpa_credit = 0.0
    score_total = 0.0
    score_credit = 0.0
    incomplete = 0
    courses = 0
    for row in rows:
        credit = _finite_number(row.get("coursePoint"))
        if credit is None or credit <= 0:
            incomplete += 1
            continue
        courses += 1
        total_credit += credit
        gpa = _finite_number(row.get("gpa"))
        score = _finite_number(row.get("score"))
        if gpa is not None:
            gpa_total += gpa * credit
            gpa_credit += credit
        if score is not None:
            score_total += score * credit
            score_credit += credit
        if gpa is None or score is None:
            incomplete += 1
    if total_credit <= 0:
        return None
    return ScoreStatistics(
        total_credit=total_credit,
        weighted_gpa=gpa_total / gpa_credit if gpa_credit else None,
        weighted_average=score_total / score_credit if score_credit else None,
        incomplete_count=incomplete,
        course_count=courses,
    )


def _finite_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
