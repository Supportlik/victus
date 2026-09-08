"""T-DOM-005: quality grade of a rolling window."""

import pytest

from victus.domain.services.reliability import grade
from victus.domain.values import Quality

pytestmark = pytest.mark.domain


@pytest.mark.parametrize(
    ("days", "coverage", "without_macros", "expected"),
    [
        (3, 100, 0, Quality.RED),
        (7, 40, 0, Quality.RED),
        (7, 100, 0, Quality.YELLOW),
        (14, 60, 0, Quality.YELLOW),
        (14, 100, 2, Quality.YELLOW),
        (14, 70, 1, Quality.GREEN),
        (30, 100, 0, Quality.GREEN),
    ],
)
def test_grade(days: int, coverage: int, without_macros: int, expected: Quality) -> None:
    assert grade(days, coverage, without_macros) is expected
