"""
Entry point for the quarterly scrape. Run as:

    python run.py

Requires environment variables SUPABASE_URL and SUPABASE_SERVICE_KEY
(see .github/workflows/scrape.yml for how these get set from GitHub
Secrets).

What this does, per symbol:
  1. Ask NSE for the latest quarterly shareholding filing (cheap call).
  2. If we've already ingested that exact quarter for this symbol, skip
     the expensive download+parse and move on.
  3. Otherwise download the filing and parse out every named holder row.
  4. For each holder row, try to match it against your watchlist:
       - exact match  -> compute new/added/sold/existing, write to holdings
       - fuzzy match  -> write to review_queue for you to confirm
       - no match     -> ignore (not someone you're tracking)
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
from xbrl_parser import parse_filing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("run")


def normalise_quarter_end(raw_date: str) -> str:
    """NSE dates come as e.g. '31-DEC-2025' - convert to ISO for Postgres."""
    return datetime.strptime(raw_date, "%d-%b-%Y").date().isoformat()


def main() -> None:
    supa = db.get_client()
    watchlist = db.load_watchlist(supa)
    if not watchlist:
        log.error("watchlist_entities is empty - nothing to match against. Add entities first.")
        sys.exit(1)
    log.info("Loaded %d watchlist entities across %d investors", len(watchlist), len({w.investor for w in watchlist}))

    stats = {"symbols_total": 0, "symbols_ok": 0, "symbols_failed": 0, "new_holdings": 0, "review_added": 0}

    with TemporaryDirectory() as tmpdir, NSE(download_folder=tmpdir, server=True) as nse:
        symbols = nse_client.get_symbol_universe(nse, Path(tmpdir))
        stats["symbols_total"] = len(symbols)
        log.info("Scanning %d symbols", len(symbols))

        for record in nse_client.iter_latest_shareholding_filings(nse, symbols):
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
                log.warning("%s: failed to fetch/parse filing: %s", symbol, e)
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
                log.info("%s: %s via %s -> %.2f%% (%s)", symbol, entity.investor, entity.entity, holder.pct, diff.status)

            stats["symbols_ok"] += 1

    db.log_run(supa, run_started=datetime.utcnow().isoformat(), **stats)
    log.info("Run complete: %s", stats)


if __name__ == "__main__":
    main()
