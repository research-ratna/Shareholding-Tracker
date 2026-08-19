"""
Entry point for the scrape. Run as:

    python run.py              # daily mode: latest quarter only, full symbol
                                # universe (investors) + full history for the
                                # company watchlist (small, so always thorough)
    python run.py --backfill   # also walks back through investor-side
                                # history across the FULL symbol universe -
                                # expensive, meant to be run manually/rarely,
                                # not on the daily schedule (see backfill.yml)

Requires environment variables SUPABASE_URL and SUPABASE_SERVICE_KEY
(see .github/workflows/scrape.yml for how these get set from GitHub
Secrets).

Two independent phases, sharing one NSE session:

  1. INVESTOR side (existing): scan symbols, parse named holder rows,
     match against your investor watchlist, write new/added/sold/existing
     to sht_holdings. In --backfill mode this walks every quarter
     .shareholding() returns per symbol instead of just the latest.

  2. COMPANY side (new): for your company watchlist, parse EVERY quarter
     .shareholding() returns into Promoter/FII/DII/Public/Other totals,
     write to sht_category_holdings. Always does full history - the
     watchlist is small enough that this doesn't need a separate backfill
     mode the way the investor side does.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from nse import NSE

import db
import nse_client
from diff import compute_status
from matcher import match_holder
from xbrl_parser import parse_category_summary, parse_filing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("run")

# If a quarter's bucket percentages don't sum close to 100%, something's
# probably misclassified or double-counted - log it rather than staying
# quiet, so a parsing problem surfaces instead of just being wrong.
CATEGORY_RECONCILE_TOLERANCE = 2.0


def normalise_quarter_end(raw_date: str) -> str:
    """NSE dates come as e.g. '31-DEC-2025' - convert to ISO for Postgres."""
    return datetime.strptime(raw_date, "%d-%b-%Y").date().isoformat()


def run_investor_side(supa, nse, tmpdir: str, backfill: bool) -> dict:
    watchlist = db.load_watchlist(supa)
    stats = {"symbols_total": 0, "symbols_ok": 0, "symbols_failed": 0, "new_holdings": 0, "review_added": 0}

    if not watchlist:
        log.warning("watchlist_entities is empty - skipping investor-side scan (nothing to match against)")
        return stats

    log.info(
        "Loaded %d watchlist entities across %d investors", len(watchlist), len({w.investor for w in watchlist})
    )

    symbols = nse_client.get_symbol_universe(nse, Path(tmpdir))
    stats["symbols_total"] = len(symbols)
    mode = "ALL historical quarters (backfill)" if backfill else "latest quarter only"
    log.info("Scanning %d symbols, %s", len(symbols), mode)

    fetcher = (
        nse_client.iter_all_shareholding_filings(nse, symbols, latest_only=False)
        if backfill
        else nse_client.iter_latest_shareholding_filings(nse, symbols)
    )

    for record in fetcher:
        symbol = record["symbol"]
        xbrl_url = record.get("xbrl")
        raw_date = record.get("date")

        if not xbrl_url or not raw_date:
            log.debug("%s: no filing data, skipping", symbol)
            continue

        try:
            quarter_end = normalise_quarter_end(raw_date)
        except ValueError:
            log.warning("%s: unrecognised date format %r, skipping", symbol, raw_date)
            stats["symbols_failed"] += 1
            continue

        if db.has_processed_quarter(supa, symbol, quarter_end):
            stats["symbols_ok"] += 1
            continue

        try:
            filing_path = nse_client.download_filing(nse, xbrl_url, Path(tmpdir))
            holder_rows = parse_filing(filing_path)
        except Exception as e:  # noqa: BLE001 - one bad filing shouldn't kill the run
            log.warning("%s (%s): failed to fetch/parse filing: %s", symbol, quarter_end, e)
            stats["symbols_failed"] += 1
            continue

        company = record.get("desc") or record.get("name") or symbol

        for holder in holder_rows:
            match = match_holder(holder.name, watchlist)
            if match is None:
                continue

            if match.needs_review:
                db.add_review_item(
                    supa,
                    symbol=symbol,
                    company=company,
                    raw_holder_name=holder.name,
                    category=holder.category,
                    pct=holder.pct,
                    shares=holder.shares,
                    quarter_end=quarter_end,
                    candidate_watchlist_id=match.watchlist_entity.id,
                    similarity=match.similarity,
                )
                stats["review_added"] += 1
                continue

            entity = match.watchlist_entity
            prev_pct = db.get_previous_pct(supa, symbol, entity.entity, quarter_end)
            diff = compute_status(holder.pct, prev_pct)

            db.upsert_holding(
                supa,
                dict(
                    symbol=symbol,
                    company=company,
                    entity=entity.entity,
                    investor=entity.investor,
                    watchlist_id=entity.id,
                    category=holder.category,
                    pct=holder.pct,
                    shares=holder.shares,
                    prev_pct=diff.prev_pct,
                    quarter_end=quarter_end,
                    status=diff.status,
                    source_url=xbrl_url,
                ),
            )
            stats["new_holdings"] += 1
            log.info(
                "%s (%s): %s via %s -> %.2f%% (%s)",
                symbol, quarter_end, entity.investor, entity.entity, holder.pct, diff.status,
            )

        db.mark_processed_filing(supa, symbol, quarter_end)
        stats["symbols_ok"] += 1

    return stats


def run_company_side(supa, nse, tmpdir: str) -> dict:
    stats = {"companies_total": 0, "companies_ok": 0, "companies_failed": 0, "category_rows_written": 0}

    company_symbols = db.load_company_watchlist(supa)
    if not company_symbols:
        log.info("company_watchlist is empty - skipping company-side scan")
        return stats

    stats["companies_total"] = len(company_symbols)
    log.info("Scanning %d companies on the watchlist, full available history", len(company_symbols))

    for record in nse_client.iter_all_shareholding_filings(nse, company_symbols, latest_only=False):
        symbol = record["symbol"]
        xbrl_url = record.get("xbrl")
        raw_date = record.get("date")

        if not xbrl_url or not raw_date:
            continue

        try:
            quarter_end = normalise_quarter_end(raw_date)
        except ValueError:
            log.warning("%s: unrecognised date format %r, skipping", symbol, raw_date)
            stats["companies_failed"] += 1
            continue

        if db.has_category_data(supa, symbol, quarter_end):
            stats["companies_ok"] += 1
            continue

        try:
            filing_path = nse_client.download_filing(nse, xbrl_url, Path(tmpdir))
            holder_rows = parse_filing(filing_path)
            category_rows = parse_category_summary(filing_path, holder_rows)
        except Exception as e:  # noqa: BLE001 - one bad filing shouldn't kill the run
            log.warning("%s (%s): failed to fetch/parse filing: %s", symbol, quarter_end, e)
            stats["companies_failed"] += 1
            continue

        company = record.get("desc") or record.get("name") or symbol
        db.set_company_name(supa, symbol, company)

        pct_sum = sum(r.pct for r in category_rows)
        if category_rows and abs(pct_sum - 100.0) > CATEGORY_RECONCILE_TOLERANCE:
            log.warning(
                "%s (%s): bucket percentages sum to %.2f%%, not ~100%% - likely a parsing issue, check manually",
                symbol, quarter_end, pct_sum,
            )

        for row in category_rows:
            prev_pct = db.get_previous_category_pct(supa, symbol, row.bucket, quarter_end)
            diff = compute_status(row.pct, prev_pct)
            db.upsert_category_holding(
                supa,
                dict(
                    symbol=symbol,
                    company=company,
                    category_bucket=row.bucket,
                    category_raw=row.source,
                    pct=row.pct,
                    shares=row.shares,
                    prev_pct=diff.prev_pct,
                    quarter_end=quarter_end,
                    status=diff.status,
                    source_url=xbrl_url,
                ),
            )
            stats["category_rows_written"] += 1

        log.info(
            "%s (%s): %d bucket(s) written (%s)",
            symbol, quarter_end, len(category_rows), ", ".join(f"{r.bucket}={r.pct:.2f}%" for r in category_rows),
        )
        stats["companies_ok"] += 1

    return stats


def main() -> None:
    backfill = "--backfill" in sys.argv
    supa = db.get_client()

    with TemporaryDirectory() as tmpdir, NSE(download_folder=tmpdir, server=True) as nse:
        investor_stats = run_investor_side(supa, nse, tmpdir, backfill=backfill)
        company_stats = run_company_side(supa, nse, tmpdir)

    all_stats = {**investor_stats, **company_stats}
    db.log_run(supa, run_started=datetime.utcnow().isoformat(), notes=("backfill" if backfill else "daily"), **{
        k: v for k, v in all_stats.items()
        if k in ("symbols_total", "symbols_ok", "symbols_failed", "new_holdings", "review_added")
    })
    log.info("Run complete. Investor side: %s | Company side: %s", investor_stats, company_stats)


if __name__ == "__main__":
    main()
