"""
Computes the status (new / added / sold / existing) for one matched holding
by comparing it against the most recent PRIOR quarter already in the
database for that exact (symbol, entity) pair.

Deliberately compares against "most recent prior quarter on file", not
"last quarter" by date subtraction - if a scrape run is missed or a
company files late, we don't want a gap to be misread as an exit-then-
re-entry. See db.get_previous_holding() for how that lookup works.

A small tolerance (PCT_TOLERANCE) absorbs rounding noise and bonus/split
adjustments that shift share counts without any real buying or selling.
"""

from dataclasses import dataclass
from typing import Optional

PCT_TOLERANCE = 0.05  # percentage points


@dataclass
class DiffResult:
    status: str  # "new" | "added" | "sold" | "existing"
    prev_pct: Optional[float]


def compute_status(current_pct: float, prev_pct: Optional[float]) -> DiffResult:
    if prev_pct is None:
        return DiffResult(status="new", prev_pct=None)

    delta = current_pct - prev_pct

    if delta > PCT_TOLERANCE:
        return DiffResult(status="added", prev_pct=prev_pct)
    if delta < -PCT_TOLERANCE:
        return DiffResult(status="sold", prev_pct=prev_pct)
    return DiffResult(status="existing", prev_pct=prev_pct)
