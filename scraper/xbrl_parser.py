"""
Parses one shareholding-pattern filing (as downloaded from the `xbrl` URL
NSE returns) and extracts the named holder rows: promoters (always named)
and public shareholders holding more than 1%.

*** READ THIS BEFORE TRUSTING THIS AT SCALE ***
This file has two parsing strategies:

1. parse_html() - parses the filing as an HTML table. I verified this
   structure directly against a live NSE filing (a company's iXBRL-rendered
   "PAN Promoter and more than 1% Shareholding Pattern" table) while
   building this, and it matches exactly what's implemented below. If NSE
   ever serves you an HTML/iXBRL rendering instead of raw XML, this path
   will work as-is.

2. parse_xml() - parses the filing as raw XBRL XML. NSE's `.shareholding()`
   call returns a `.xml` link, so this is the path you'll hit most often.
   I do NOT have a verified list of the exact XBRL taxonomy tag names NSE
   uses (couldn't reach nseindia.com's servers from the sandbox this was
   built in), so this groups facts by their shared `contextRef` (the
   standard way XBRL represents "one row of a repeating table") and then
   classifies each fact by keyword-matching its tag's local name. This is
   a reasonable, defensible approach, but it is a best guess on exact
   spelling, not a verified one.

   BEFORE RUNNING THIS AT SCALE: run parse_xml() against 3-5 real
   downloaded filings, print the result, and compare against what the
   company actually filed (visible on the NSE website for that company).
   If rows come back empty or wrong, the fix is almost always just
   widening the keyword lists in _classify_tag() below - the grouping
   logic itself doesn't need to change.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from lxml import etree

log = logging.getLogger("xbrl_parser")


@dataclass
class HolderRow:
    category: str
    name: str
    shares: int
    pct: float
    pan: Optional[str] = None


# Keyword sets used to classify an XBRL fact's local tag name (or an HTML
# table's column header) into one of our fields. Order matters within each
# list - more specific keywords should come first.
_NAME_KEYWORDS = ["nameoftheshareholders", "nameofshareholder", "shareholdername"]
_PAN_KEYWORDS = ["permanentaccountnumber", "pan"]
_SHARES_KEYWORDS = [
    "numberoffullypaidupequityshares",
    "totalnosshares",
    "numberofsharesheld",
]
_SHARES_EXCLUDE = ["voting", "locked", "pledged", "underlying", "convertible", "warrant", "demat"]
_PCT_KEYWORDS = ["shareholdingasapercentageoftotalnumberofshares", "percentageoftotalnumberofshares"]
_PCT_EXCLUDE = ["voting", "diluted"]
_CATEGORY_KEYWORDS = ["categoryofshareholder", "category"]


def _classify_tag(local_name: str) -> Optional[str]:
    t = local_name.lower()
    if any(k in t for k in _NAME_KEYWORDS):
        return "name"
    if any(k in t for k in _PAN_KEYWORDS):
        return "pan"
    if any(k in t for k in _SHARES_KEYWORDS) and not any(x in t for x in _SHARES_EXCLUDE):
        return "shares"
    if any(k in t for k in _PCT_KEYWORDS) and not any(x in t for x in _PCT_EXCLUDE):
        return "pct"
    if any(k in t for k in _CATEGORY_KEYWORDS):
        return "category"
    return None


def parse_xml(path: Path) -> list[HolderRow]:
    """Strategy 1: raw XBRL instance document. See module docstring."""
    tree = etree.parse(str(path))
    root = tree.getroot()

    contexts: dict[str, dict[str, str]] = {}
    for el in root.iter():
        ctx_ref = el.get("contextRef")
        if not ctx_ref:
            continue
        local = etree.QName(el).localname
        field = _classify_tag(local)
        if not field:
            continue
        text = (el.text or "").strip()
        if not text:
            continue
        contexts.setdefault(ctx_ref, {})[field] = text

    rows = []
    for ctx_ref, fields in contexts.items():
        if "name" not in fields or "shares" not in fields or "pct" not in fields:
            continue
        try:
            rows.append(
                HolderRow(
                    category=fields.get("category", ""),
                    name=_clean_name(fields["name"]),
                    shares=_to_int(fields["shares"]),
                    pct=_to_float(fields["pct"]),
                    pan=fields.get("pan"),
                )
            )
        except ValueError:
            log.warning("Could not parse row for context %s: %s", ctx_ref, fields)

    if not rows:
        log.warning(
            "parse_xml found 0 rows in %s - the tag-name guesses in "
            "_classify_tag() likely need adjusting against this file.",
            path,
        )
    return rows


def parse_html(path: Path) -> list[HolderRow]:
    """Strategy 2: iXBRL rendered as HTML. See module docstring."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    rows: list[HolderRow] = []

    for table in soup.find_all("table"):
        header_cells = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        header_text = " ".join(header_cells)
        if "name of the shareholder" not in header_text and "pan" not in header_text:
            continue  # not the table we want

        col_index = {}
        header_row = table.find("tr")
        for i, cell in enumerate(header_row.find_all(["th", "td"])):
            label = cell.get_text(" ", strip=True).lower()
            if "name of the shareholder" in label:
                col_index["name"] = i
            elif label == "pan" or "permanent account" in label:
                col_index["pan"] = i
            elif "category" in label:
                col_index["category"] = i
            elif "fully paid up equity shares held" in label:
                col_index["shares"] = i
            elif "shareholding as a %" in label:
                col_index["pct"] = i

        if "name" not in col_index or "shares" not in col_index or "pct" not in col_index:
            continue

        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(col_index.values()):
                continue
            name = cells[col_index["name"]].get_text(" ", strip=True)
            if not name:
                continue
            try:
                shares = _to_int(cells[col_index["shares"]].get_text(strip=True))
                pct = _to_float(cells[col_index["pct"]].get_text(strip=True))
            except ValueError:
                continue
            rows.append(
                HolderRow(
                    category=cells[col_index.get("category", 0)].get_text(" ", strip=True),
                    name=_clean_name(name),
                    shares=shares,
                    pct=pct,
                    pan=cells[col_index["pan"]].get_text(strip=True) if "pan" in col_index else None,
                )
            )
        break  # found and parsed the right table

    return rows


def parse_filing(path: Path) -> list[HolderRow]:
    """Auto-detect XML vs HTML and dispatch to the right strategy."""
    head = path.read_text(encoding="utf-8", errors="ignore")[:500].lstrip()
    if head.startswith("<?xml") or head.startswith("<xbrl"):
        return parse_xml(path)
    return parse_html(path)


def _clean_name(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip()


def _to_int(raw: str) -> int:
    cleaned = re.sub(r"[,\s]", "", raw)
    if cleaned in ("", "-", "0.0"):
        return 0
    return int(float(cleaned))


def _to_float(raw: str) -> float:
    cleaned = re.sub(r"[,\s%]", "", raw)
    if cleaned in ("", "-"):
        return 0.0
    return float(cleaned)
