"""
Thin wrapper around the `nse` package (BennyThadikaran/NseIndiaApi).

Responsible for:
  - getting the full universe of NSE equity symbols
  - fetching each symbol's quarterly shareholding filing list (which
    includes a link to the underlying XBRL document)
  - downloading a given XBRL filing using the library's authenticated
    session, so we don't get blocked by NSE's anti-bot layer

This module deliberately does NOT parse the XBRL content — that's
xbrl_parser.py. Keeping the "talk to NSE" and "understand the filing"
concerns separate makes it much easier to fix the parser later without
touching anything network-related.
"""

import csv
import io
import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

from nse import NSE

log = logging.getLogger("nse_client")

# NSE throttles to ~3 req/sec on its own side. This sleep is a courtesy on
# top of that so we don't hammer it during a 2,000-symbol loop.
REQUEST_DELAY_SECONDS = 0.4


def get_symbol_universe(nse: NSE, download_folder: Path) -> list[str]:
    """
    Full list of currently traded NSE equity symbols, sourced from the most
    recent daily bhavcopy (every symbol that traded that day). This is the
    standard way to get "every listed company" rather than just an index's
    constituents.
    """
    # Bhavcopy isn't published same-day until after market close; walk
    # backwards a few days to find the most recent one that's ready.
    for days_back in range(0, 6):
        d = date.today() - timedelta(days=days_back)
        if d.weekday() >= 5:  # skip weekends
            continue
        try:
            path = nse.equityBhavcopy(d, folder=download_folder)
            break
        except (FileNotFoundError, RuntimeError):
            continue
    else:
        raise RuntimeError("Could not find a recent bhavcopy in the last 6 days")

    symbols: set[str] = set()
    with open(path, newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        # Column name varies slightly between old/new bhavcopy formats.
        symbol_col = next(
            (c for c in reader.fieldnames or [] if c.strip().upper() in ("SYMBOL", "TCKRSYMB")),
            None,
        )
        if symbol_col is None:
            raise RuntimeError(f"Unrecognised bhavcopy columns: {reader.fieldnames}")
        series_col = next(
            (c for c in reader.fieldnames or [] if c.strip().upper() in ("SERIES", "SCTYS_MRKT_TYPE")),
            None,
        )
        for row in reader:
            # Restrict to the plain "EQ" series to avoid debt instruments,
            # SGBs etc. that don't file a shareholding pattern the same way.
            if series_col and row.get(series_col, "").strip().upper() not in ("EQ", ""):
                continue
            symbols.add(row[symbol_col].strip())

    log.info("Found %d symbols in bhavcopy for %s", len(symbols), d.isoformat())
    return sorted(symbols)


def iter_latest_shareholding_filings(nse: NSE, symbols: list[str]) -> Iterator[dict]:
    """
    For each symbol, yield the single most recent quarterly filing record
    (the .shareholding() call already returns latest-quarter-first).

    Yields dicts with at least: symbol, company (best-effort), date
    (quarter-end as filed), xbrl (URL to the filing), recordId.
    Symbols that error out are logged and skipped, not raised, since a
    handful of failures shouldn't abort a 2,000-symbol run.
    """
    for symbol in symbols:
        try:
            records = nse.shareholding(symbol)
        except Exception as e:  # noqa: BLE001 - deliberately broad, this loops 2000x
            log.warning("shareholding() failed for %s: %s", symbol, e)
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        if not records:
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        latest = records[0]
        latest["symbol"] = symbol
        yield latest
        time.sleep(REQUEST_DELAY_SECONDS)


def download_filing(nse: NSE, xbrl_url: str, folder: Path) -> Path:
    """Download one XBRL filing using the library's authenticated session."""
    return nse.download_document(xbrl_url, folder=folder)
