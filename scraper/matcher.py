"""
Matches a holder name found in a filing (e.g. "MEHTA FAMILY TRUST") against
your watchlist_entities table.

Two tiers, deliberately not blended into one fuzzy score:

  - Exact match (case/whitespace-insensitive): auto-attributed straight to
    the matching watchlist entity. No human in the loop needed - "Mehta
    Family Trust" and "MEHTA FAMILY TRUST" are obviously the same entity.

  - Fuzzy match above FUZZY_THRESHOLD but not exact: written to
    review_queue instead of auto-attributed. A stake is real money; a
    fuzzy-matched name should get your eyes on it once, not silently
    become a signal because two names happened to be similar.

Below FUZZY_THRESHOLD: ignored entirely. Most filings are full of
shareholders that have nothing to do with your watchlist - we don't want
review_queue to fill up with noise.
"""

from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz

FUZZY_THRESHOLD = 88.0  # 0-100. Raise this if review_queue fills with junk;
                         # lower it if real matches are being missed entirely.


@dataclass
class WatchlistEntity:
    id: int
    investor: str
    entity: str


@dataclass
class MatchResult:
    watchlist_entity: Optional[WatchlistEntity]
    similarity: float
    needs_review: bool


def _normalise(name: str) -> str:
    return " ".join(name.strip().upper().split())


def match_holder(holder_name: str, watchlist: list[WatchlistEntity]) -> Optional[MatchResult]:
    """
    Returns None if the holder isn't a plausible match for anything on the
    watchlist (below threshold) - the caller should just skip it.
    """
    target = _normalise(holder_name)

    best: Optional[WatchlistEntity] = None
    best_score = 0.0
    for candidate in watchlist:
        score = fuzz.ratio(target, _normalise(candidate.entity))
        if score > best_score:
            best_score = score
            best = candidate

    if best is None or best_score < FUZZY_THRESHOLD:
        return None

    is_exact = best_score >= 99.9  # rapidfuzz gives 100 for identical strings
    return MatchResult(watchlist_entity=best, similarity=best_score, needs_review=not is_exact)
