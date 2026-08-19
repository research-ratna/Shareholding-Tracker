"""
All Supabase reads/writes go through this module, so the rest of the
scraper never has to know the table shapes directly.

Expects SUPABASE_URL and SUPABASE_SERVICE_KEY as environment variables
(set as GitHub Actions secrets - see .github/workflows/scrape.yml).
Uses the service-role key, not the anon key, because this writes data;
the Next.js dashboard uses the anon key for reads instead.
"""

import os
from typing import Optional

from supabase import Client, create_client

from matcher import WatchlistEntity


def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


def load_watchlist(db: Client) -> list[WatchlistEntity]:
    res = db.table("sht_watchlist_entities").select("id, investor, entity").execute()
    return [WatchlistEntity(id=r["id"], investor=r["investor"], entity=r["entity"]) for r in res.data]


def get_previous_pct(db: Client, symbol: str, entity: str, before_quarter: str) -> Optional[float]:
    """
    Most recent holding for this exact (symbol, entity) strictly before
    `before_quarter` (an ISO date string, e.g. "2026-06-30"). Returns None
    if we've never seen this entity hold this stock before - i.e. a
    genuinely new entry, not a data gap.
    """
    res = (
        db.table("sht_holdings")
        .select("pct, quarter_end")
        .eq("symbol", symbol)
        .eq("entity", entity)
        .lt("quarter_end", before_quarter)
        .order("quarter_end", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    return float(res.data[0]["pct"])


def has_processed_quarter(db: Client, symbol: str, quarter_end: str) -> bool:
    """
    True if we already have at least one holdings row for this symbol and
    quarter. Used to skip the (slow) download+parse step on repeat runs
    within the same filing window - the cheap .shareholding() summary call
    still happens every run so we notice as soon as a new quarter appears.
    """
    res = (
        db.table("sht_holdings")
        .select("id")
        .eq("symbol", symbol)
        .eq("quarter_end", quarter_end)
        .limit(1)
        .execute()
    )
    return len(res.data) > 0


def upsert_holding(db: Client, row: dict) -> None:
    """
    row keys: symbol, company, entity, investor, watchlist_id, category,
    pct, shares, prev_pct, quarter_end, status, source_url
    Unique on (symbol, entity, quarter_end) - re-running the same quarter
    overwrites rather than duplicates.
    """
    db.table("sht_holdings").upsert(row, on_conflict="symbol,entity,quarter_end").execute()


def add_review_item(db: Client, row: dict) -> None:
    """
    row keys: symbol, company, raw_holder_name, category, pct, shares,
    quarter_end, candidate_watchlist_id, similarity
    """
    db.table("sht_review_queue").insert(row).execute()


def log_run(db: Client, **kwargs) -> None:
    db.table("sht_scrape_log").insert(kwargs).execute()
