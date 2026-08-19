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
    True if this (symbol, quarter) filing has already been downloaded and
    parsed - regardless of whether anything in it matched a watchlist.
    Used to skip the (slow) download+parse step on repeat runs; the cheap
    .shareholding() summary call still happens every run so we notice as
    soon as a new quarter appears.

    Checks sht_processed_filings, NOT sht_holdings: sht_holdings only gets
    a row when something actually matches your watchlist, so keying this
    check off it (the original approach) meant the ~2000 symbols that
    never match anything were re-downloaded and re-parsed on every single
    run, forever. mark_processed_filing() below is what populates this.
    """
    res = (
        db.table("sht_processed_filings")
        .select("symbol")
        .eq("symbol", symbol)
        .eq("quarter_end", quarter_end)
        .limit(1)
        .execute()
    )
    return len(res.data) > 0


def mark_processed_filing(db: Client, symbol: str, quarter_end: str) -> None:
    """Call this once a filing has been downloaded and parsed, whether or
    not it matched anything - see has_processed_quarter()."""
    db.table("sht_processed_filings").upsert(
        {"symbol": symbol, "quarter_end": quarter_end}, on_conflict="symbol,quarter_end"
    ).execute()


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


# ---------------------------------------------------------------------------
# Company tracker (reverse direction): Promoter/FII/DII/Public by company.
# ---------------------------------------------------------------------------


def load_company_watchlist(db: Client) -> list[str]:
    """Just the symbols - that's all run.py needs to know what to fetch."""
    res = db.table("sht_company_watchlist").select("symbol").execute()
    return [r["symbol"] for r in res.data]


def set_company_name(db: Client, symbol: str, company: str) -> None:
    """Fills in the display name the first time we successfully fetch a
    symbol on the company watchlist - rows are added with just a symbol."""
    db.table("sht_company_watchlist").update({"company": company}).eq("symbol", symbol).execute()


def has_category_data(db: Client, symbol: str, quarter_end: str) -> bool:
    """
    True if category holdings are already written for this (symbol,
    quarter). Deliberately its OWN check, not has_processed_quarter():
    a symbol can be scanned on the investor side (which marks it
    "processed") without ever going through category-summary parsing, so
    sharing that flag would make the company side silently skip work it
    hasn't actually done yet.
    """
    res = (
        db.table("sht_category_holdings")
        .select("id")
        .eq("symbol", symbol)
        .eq("quarter_end", quarter_end)
        .limit(1)
        .execute()
    )
    return len(res.data) > 0


def get_previous_category_pct(
    db: Client, symbol: str, category_bucket: str, before_quarter: str
) -> Optional[float]:
    """Same idea as get_previous_pct() above, but for one bucket of one
    company - most recent pct strictly before `before_quarter`."""
    res = (
        db.table("sht_category_holdings")
        .select("pct, quarter_end")
        .eq("symbol", symbol)
        .eq("category_bucket", category_bucket)
        .lt("quarter_end", before_quarter)
        .order("quarter_end", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    return float(res.data[0]["pct"])


def upsert_category_holding(db: Client, row: dict) -> None:
    """
    row keys: symbol, company, category_bucket, category_raw, pct, shares,
    prev_pct, quarter_end, status, source_url
    Unique on (symbol, category_bucket, quarter_end).
    """
    db.table("sht_category_holdings").upsert(row, on_conflict="symbol,category_bucket,quarter_end").execute()
