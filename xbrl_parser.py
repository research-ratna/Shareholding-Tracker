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


@dataclass
class CategoryRow:
    """One bucket's total for a company/quarter: Promoter, FII, DII, Public,
    or Other. `source` records how confident this number is - see
    classify_bucket() and parse_category_summary() docstrings."""

    bucket: str  # "promoter" | "fii" | "dii" | "public" | "other"
    shares: int
    pct: float
    source: str  # "computed_from_named_holders" | "filed_summary_table"


# The real category text NSE files (confirmed against a live ADF Foods Ltd
# filing - see fixtures/sample_filing.html and its docstring) follows this
# shape consistently: "<TopLevel> : <SubCategory>", e.g.
#   "Promoter & Promoter Group-Indian : Individuals/HUF"
#   "Public-Institution (Domestic) : Alternate Investment Funds"
#   "Public-Institution (Foreign) :Foreign Portfolio Investor Category I"
#   "Public-Non-Institution : Bodies Corporate"
# classify_bucket() matches on the TopLevel prefix, which is the part SEBI's
# format keeps stable across companies. It has NOT been verified against a
# summary-statement (Table I) row specifically, only against named-holder
# rows using the same taxonomy - validate before trusting at scale, same as
# the rest of this file.
def classify_bucket(category_text: str) -> str:
    t = category_text.lower()
    # More specific cases first: "non promoter" contains the substring
    # "promoter", so it must be checked before the plain "promoter" match
    # below, or it gets swallowed by it.
    if "non promoter" in t or "non-promoter" in t or "custodian" in t or "employee benefit" in t:
        return "other"
    if "promoter" in t:
        return "promoter"
    if "institution (foreign)" in t or "institution(foreign)" in t or "institutions (foreign)" in t:
        return "fii"
    if "institution (domestic)" in t or "institution(domestic)" in t or "institutions (domestic)" in t:
        return "dii"
    if "non-institution" in t or "non institution" in t:
        return "public"
    return "other"


def promoter_total_from_holders(holder_rows: list[HolderRow]) -> Optional[CategoryRow]:
    """
    Promoters have no 1% disclosure threshold - every promoter holder is
    individually named in the table this module already parses reliably.
    So unlike fii/dii/public/other, we don't need the (less-verified)
    summary-table path to get an exact promoter total: just sum the holder
    rows already classified as promoter. Returns None if no promoter rows
    were found (shouldn't normally happen for a real filing).
    """
    promoter_rows = [h for h in holder_rows if classify_bucket(h.category) == "promoter"]
    if not promoter_rows:
        return None
    return CategoryRow(
        bucket="promoter",
        shares=sum(h.shares for h in promoter_rows),
        pct=round(sum(h.pct for h in promoter_rows), 3),
        source="computed_from_named_holders",
    )


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


# Rows to ignore when summing Table I into bucket totals - rollup/subtotal
# lines, not leaf category lines. Summing these in alongside the leaf rows
# they roll up would double- or triple-count. This is the main risk point
# in this extraction path: if a company's filing phrases a rollup line
# without any of these words, it'll get summed in as if it were a leaf row.
_ROLLUP_KEYWORDS = ["sub-total", "subtotal", "sub total", "grand total", "total public", "total institution"]


def _sum_table_i_rows(rows: list[tuple[str, int, float]]) -> list[CategoryRow]:
    """rows: list of (category_text, shares, pct). Buckets and sums leaf
    rows only (see _ROLLUP_KEYWORDS), skipping the promoter bucket - that
    one comes from promoter_total_from_holders() instead, which is exact."""
    totals: dict[str, list[float]] = {"fii": [0, 0.0], "dii": [0, 0.0], "public": [0, 0.0], "other": [0, 0.0]}
    for category_text, shares, pct in rows:
        t = category_text.lower()
        if any(k in t for k in _ROLLUP_KEYWORDS):
            continue
        bucket = classify_bucket(category_text)
        if bucket == "promoter":
            continue  # handled separately and more reliably - see above
        totals[bucket][0] += shares
        totals[bucket][1] += pct
    return [
        CategoryRow(bucket=b, shares=int(v[0]), pct=round(v[1], 3), source="filed_summary_table")
        for b, v in totals.items()
    ]


def parse_category_summary_html(path: Path) -> list[CategoryRow]:
    """
    *** UNVERIFIED - validate against a real filing before trusting ***
    Finds the "Table I - Summary Statement" table (distinguished from the
    named-holder table by having a "category of shareholder" column and a
    "no. of shareholders" COUNT column, but no "name of the shareholder" or
    "pan" column) and sums its leaf rows into fii/dii/public/other totals.
    """
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")

    for table in soup.find_all("table"):
        header_cells = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        header_text = " ".join(header_cells)
        if "name of the shareholder" in header_text or "pan" in header_text:
            continue  # that's the named-holder table, not this one
        if "category of shareholder" not in header_text or "shareholders" not in header_text:
            continue  # not a table we recognise

        col_index: dict[str, int] = {}
        header_row = table.find("tr")
        for i, cell in enumerate(header_row.find_all(["th", "td"])):
            label = cell.get_text(" ", strip=True).lower()
            if "category of shareholder" in label:
                col_index["category"] = i
            elif "total nos" in label and "shares held" in label:
                col_index["shares"] = i
            elif "shareholding as a %" in label:
                col_index["pct"] = i

        if "category" not in col_index or "shares" not in col_index or "pct" not in col_index:
            continue

        raw_rows: list[tuple[str, int, float]] = []
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(col_index.values()):
                continue
            category_text = cells[col_index["category"]].get_text(" ", strip=True)
            if not category_text:
                continue
            try:
                shares = _to_int(cells[col_index["shares"]].get_text(strip=True))
                pct = _to_float(cells[col_index["pct"]].get_text(strip=True))
            except ValueError:
                continue
            raw_rows.append((category_text, shares, pct))

        if raw_rows:
            return _sum_table_i_rows(raw_rows)

    return []


def parse_category_summary_xml(path: Path) -> list[CategoryRow]:
    """
    *** UNVERIFIED - validate against a real filing before trusting, same
    caveat as parse_xml() above, plus an extra one: this assumes Table I's
    category text is a plain fact in the same context as its shares/pct
    facts. If NSE instead encodes it as an XBRL dimension member on the
    <context> itself (a real possibility for a structured summary table),
    this will find 0 rows and needs rework, not just wider keywords. ***
    Same contextRef-grouping approach as parse_xml(), but keeps groups that
    have category+shares+pct WITHOUT a name (that's what distinguishes a
    Table I summary row from a named-holder row).
    """
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

    raw_rows: list[tuple[str, int, float]] = []
    for fields in contexts.values():
        if "name" in fields or "category" not in fields or "shares" not in fields or "pct" not in fields:
            continue
        try:
            raw_rows.append((fields["category"], _to_int(fields["shares"]), _to_float(fields["pct"])))
        except ValueError:
            continue

    return _sum_table_i_rows(raw_rows) if raw_rows else []


def parse_category_summary(path: Path, holder_rows: list[HolderRow]) -> list[CategoryRow]:
    """
    Full bucket breakdown for one filing: promoter (computed, reliable) +
    fii/dii/public/other (parsed from Table I, unverified - see module
    docstring additions above). holder_rows should be the output of
    parse_filing() on this same path, so promoter isn't parsed twice.
    """
    result = []
    promoter = promoter_total_from_holders(holder_rows)
    if promoter:
        result.append(promoter)

    head = path.read_text(encoding="utf-8", errors="ignore")[:500].lstrip()
    if head.startswith("<?xml") or head.startswith("<xbrl"):
        result.extend(parse_category_summary_xml(path))
    else:
        result.extend(parse_category_summary_html(path))
    return result


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
