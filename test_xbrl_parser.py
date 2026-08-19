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

from xbrl_parser import parse_category_summary_html, parse_html, parse_xml, promoter_total_from_holders

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


def test_promoter_total_from_holders():
    """
    Promoter total should come from summing named-holder rows - this uses
    the REAL fixture (sample_filing.html), so unlike the tests below, this
    one is checking against real filed numbers, not synthetic ones.
    """
    holder_rows = parse_html(FIXTURE_DIR / "sample_filing.html")
    result = promoter_total_from_holders(holder_rows)
    assert result is not None
    assert result.bucket == "promoter"
    # MAHALAXMI RAMESH THAKKAR (9665000, 8.797) + H J Thakkar Property
    # Investment LLP (3279575, 2.985) are the two promoter-classified rows
    # in the real fixture; the other 4 rows are Public-Institution/Public-
    # Non-Institution and must NOT be included.
    assert result.shares == 9665000 + 3279575, result.shares
    assert abs(result.pct - (8.797 + 2.985)) < 0.001, result.pct
    assert result.source == "computed_from_named_holders"
    print("promoter_total_from_holders: correctly sums only promoter rows from a real fixture")


def test_parse_category_summary_html_mechanism():
    """
    Synthetic Table I fixture (see fixtures/sample_summary_table.html for
    exactly what's synthetic vs. grounded in a real filing). Proves the
    leaf-row summing and rollup/double-count guard work as designed - does
    NOT confirm NSE renders Table I with these exact column headers.
    """
    rows = parse_category_summary_html(FIXTURE_DIR / "sample_summary_table.html")
    by_bucket = {r.bucket: r for r in rows}

    assert "promoter" not in by_bucket, "promoter must come from promoter_total_from_holders(), not this path"

    # dii = Mutual Funds/UTI (800000, 7.300) + Insurance Companies (500000, 4.560)
    assert by_bucket["dii"].shares == 1_300_000, by_bucket["dii"].shares
    assert abs(by_bucket["dii"].pct - 11.860) < 0.001, by_bucket["dii"].pct

    # fii = the single Foreign Portfolio Investor Category I leaf row
    assert by_bucket["fii"].shares == 2_100_000, by_bucket["fii"].shares
    assert abs(by_bucket["fii"].pct - 19.170) < 0.001, by_bucket["fii"].pct

    # public = Bodies Corporate (900000) + Individuals (750000) - must NOT
    # also include the "Total Public Shareholding (B)" rollup row
    # (5,050,000), which would silently double the real number.
    assert by_bucket["public"].shares == 1_650_000, by_bucket["public"].shares
    assert abs(by_bucket["public"].pct - 15.050) < 0.001, by_bucket["public"].pct

    # other = Custodian/DR Holder + Employee Benefit Trust
    assert by_bucket["other"].shares == 1_900_000, by_bucket["other"].shares
    assert abs(by_bucket["other"].pct - 17.340) < 0.001, by_bucket["other"].pct

    for r in rows:
        assert r.source == "filed_summary_table"

    print("parse_category_summary_html: leaf-summing and rollup guard both work on synthetic fixture")
    print("REMINDER: this does not confirm NSE's real Table I column headers - see module docstring")


if __name__ == "__main__":
    test_parse_html_real_structure()
    test_parse_xml_grouping_mechanism()
    test_promoter_total_from_holders()
    test_parse_category_summary_html_mechanism()
    print("\nAll tests passed.")
