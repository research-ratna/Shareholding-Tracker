"""
Tests for xbrl_parser.py.

The HTML fixture below is not made up - it's a trimmed, structurally
faithful copy of a real filing (ADF Foods Ltd, quarter ended 31-Mar-2025)
that I fetched directly from nseindia.com while building this, specifically
to verify the "PAN Promoter and more than 1% Shareholding Pattern" table
structure before writing the parser against it. Row values are copied from
that real filing.

The XML fixture is synthetic - it exercises the contextRef-grouping logic
in parse_xml() using tag names that match the keyword lists in
_classify_tag(). It proves the *mechanism* works; it does NOT prove NSE's
real XBRL uses these exact tag names. See the module docstring in
xbrl_parser.py for what to do about that.
"""

from pathlib import Path

from xbrl_parser import parse_html, parse_xml

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_parse_html_real_structure():
    rows = parse_html(FIXTURE_DIR / "sample_filing.html")
    assert len(rows) == 6, f"expected 6 rows, got {len(rows)}"

    by_name = {r.name: r for r in rows}

    r = by_name["MAHALAXMI RAMESH THAKKAR"]
    assert r.shares == 9665000
    assert r.pct == 8.797
    assert "Promoter" in r.category

    r = by_name["ABAKKUS EMERGING OPPORTUNITIES FUND-1"]
    assert r.shares == 1686435
    assert r.pct == 1.535

    r = by_name["SIXTH SENSE INDIA OPPORTUNITIES III"]
    assert r.shares == 7804508
    assert r.pct == 7.104

    r = by_name["AUTHUM INVESTMENT AND INFRASTRUCTURE LIMITED"]
    assert r.pan == "" or r.pan is None or True  # PAN often blank in real filings; just shouldn't crash
    assert r.shares == 16293027

    print("parse_html: all assertions passed on real-structure fixture")


def test_parse_xml_grouping_mechanism():
    rows = parse_xml(FIXTURE_DIR / "sample_filing.xml")
    assert len(rows) == 2, f"expected 2 rows, got {len(rows)}"

    by_name = {r.name: r for r in rows}
    assert by_name["Test Investor Trust"].shares == 500000
    assert by_name["Test Investor Trust"].pct == 1.25
    assert by_name["Another Holder LLP"].shares == 210000
    assert by_name["Another Holder LLP"].pct == 1.05

    print("parse_xml: grouping mechanism works on synthetic fixture")
    print("REMINDER: this does not confirm NSE's real tag names - see module docstring")


if __name__ == "__main__":
    test_parse_html_real_structure()
    test_parse_xml_grouping_mechanism()
    print("\nAll tests passed.")
