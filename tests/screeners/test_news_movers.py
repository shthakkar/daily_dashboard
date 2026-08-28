import pandas as pd
import pytest
from bs4 import BeautifulSoup

from screeners.news_movers import _page_count, _parse_number, _parse_rows, _rows_from_df


def _make_df():
    # `_rows_from_df` receives already-clean tickers -- `_fetch`/`_parse_rows`
    # own turning Finviz's decorated cell text into a plain symbol. Price,
    # Volume, Avg Volume and Rel Volume are floats (as `_parse_number`
    # produces them); "Change %" stays a raw percent string, matching what
    # `_parse_rows` puts in that column. Rel Volume order deliberately
    # differs from Change % order so sorting by the wrong column would be
    # caught. All three clear the $300M dollar volume (Price * Volume)
    # highlight threshold.
    return pd.DataFrame({
        "Ticker":      ["HOWL", "MRNA", "GRML"],
        "Price":       [10.0, 20.0, 15.0],
        "Change %":    ["102.57%", "8.86%", "22.11%"],
        "Volume":      [100_000_000.0, 50_000_000.0, 80_000_000.0],
        "Avg Volume":  [12_000_000.0, 30_000_000.0, 5_000_000.0],
        "Rel Volume":  [3.1, 4.2, 3.8],
    })


def test_rows_from_df_formats_fields():
    rows = _rows_from_df(_make_df())
    top = next(r for r in rows if r["ticker"] == "HOWL")
    assert top["price"] == "$10.00"
    assert top["change"] == "+102.57%"
    assert top["volume"] == "100.0M"
    assert top["avg_volume"] == "12.0M"
    assert top["rel_volume"] == "3.1x"
    assert top["high_dollar_volume"] is True


def test_rows_from_df_sorted_by_rel_volume_descending():
    rows = _rows_from_df(_make_df())
    assert [r["ticker"] for r in rows] == ["MRNA", "GRML", "HOWL"]


def test_rows_from_df_none_returns_empty():
    assert _rows_from_df(None) == []


def test_rows_from_df_empty_df_returns_empty():
    assert _rows_from_df(pd.DataFrame()) == []


def test_rows_from_df_keeps_all_rows_but_flags_dollar_volume():
    df = pd.DataFrame({
        "Ticker":     ["AAA", "BBB"],
        "Price":      [10.0, 1.0],
        "Change %":   ["5.00%", "5.00%"],
        "Volume":     [100_000_000.0, 10_000_000.0],  # $1B vs $10M
        "Avg Volume": [1_000_000.0, 1_000_000.0],
        "Rel Volume": [3.5, 3.6],
    })
    rows = _rows_from_df(df)
    assert [r["ticker"] for r in rows] == ["BBB", "AAA"]
    high = {r["ticker"]: r["high_dollar_volume"] for r in rows}
    assert high == {"AAA": True, "BBB": False}


def test_rows_from_df_dollar_volume_exactly_at_threshold_not_flagged():
    df = pd.DataFrame({
        "Ticker":     ["AAA"],
        "Price":      [30.0],
        "Change %":   ["5.00%"],
        "Volume":     [10_000_000.0],  # exactly $300M
        "Avg Volume": [1_000_000.0],
        "Rel Volume": [3.5],
    })
    rows = _rows_from_df(df)
    assert rows[0]["high_dollar_volume"] is False


def test_rows_from_df_missing_price_or_volume_not_flagged_but_kept():
    df = pd.DataFrame({
        "Ticker":     ["T0"],
        "Price":      [float("nan")],
        "Change %":   ["5.00%"],
        "Volume":     [100_000_000.0],
        "Avg Volume": [1_000_000.0],
        "Rel Volume": [3.0],
    })
    rows = _rows_from_df(df)
    assert rows[0]["ticker"] == "T0"
    assert rows[0]["price"] == "N/A"
    assert rows[0]["high_dollar_volume"] is False


def test_rows_from_df_handles_nan_in_non_filter_fields():
    df = pd.DataFrame({
        "Ticker":     ["T0"],
        "Price":      [10.0],
        "Change %":   [float("nan")],
        "Volume":     [100_000_000.0],
        "Avg Volume": [float("nan")],
        "Rel Volume": [float("nan")],
    })
    rows = _rows_from_df(df)
    assert rows[0]["ticker"] == "T0"
    assert rows[0]["price"] == "$10.00"
    assert rows[0]["change"] == "N/A"
    assert rows[0]["volume"] == "100.0M"
    assert rows[0]["avg_volume"] == "N/A"
    assert rows[0]["rel_volume"] == "N/A"


# --- _parse_number ---------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("23.25", 23.25),
    ("11,917,022", 11_917_022.0),
    ("512.57K", 512_570.0),
    ("18.5M", 18_500_000.0),
    ("1.2B", 1_200_000_000.0),
    ("-", None),
    ("", None),
])
def test_parse_number(raw, expected):
    result = _parse_number(raw)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


# --- _parse_rows / _page_count ---------------------------------------------

def _row_html(ticker_cell_text, ticker_attr=None, price="248.04", change="20.63%",
              volume="18,513,815", avg_volume="14.82M", rel_volume="7.48"):
    # `ticker_attr`, when given, mirrors Finviz's real markup: the
    # `data-boxover-ticker` attribute lives on the <td> itself.
    attr = f' data-boxover-ticker="{ticker_attr}"' if ticker_attr else ""
    return f"""
      <tr>
        <td>1</td>
        <td{attr}>{ticker_cell_text}</td>
        <td>{price}</td>
        <td>{change}</td>
        <td>{volume}</td>
        <td>{avg_volume}</td>
        <td>{rel_volume}</td>
      </tr>
    """


def _table_soup(*row_htmls):
    header = "<tr><th>No.</th><th>Ticker</th><th>Price</th><th>Change %</th><th>Volume</th><th>Avg Volume</th><th>Rel Volume</th></tr>"
    html = f'<table class="screener_table">{header}{"".join(row_htmls)}</table>'
    return BeautifulSoup(html, "html.parser")


def test_parse_rows_uses_data_boxover_ticker_even_when_cell_text_is_mangled():
    # Regression case: Finviz's avatar fallback text came back longer than
    # the usual one character, so the visible cell text is "CCRM" for
    # Salesforce -- but the data attribute is still the plain symbol.
    row = _row_html("CCRM", ticker_attr="CRM")
    soup = _table_soup(row)
    records = _parse_rows(soup)
    assert records[0]["Ticker"] == "CRM"
    assert records[0]["Price"] == 248.04
    assert records[0]["Volume"] == 18_513_815.0
    assert records[0]["Avg Volume"] == 14_820_000.0
    assert records[0]["Rel Volume"] == 7.48
    assert records[0]["Change %"] == "20.63%"


def test_parse_rows_falls_back_to_strip_when_data_attribute_missing():
    row = _row_html("HHOWL")  # no data-boxover-ticker attribute anywhere
    soup = _table_soup(row)
    records = _parse_rows(soup)
    assert records[0]["Ticker"] == "HOWL"


def test_parse_rows_skips_short_rows():
    soup = BeautifulSoup(
        '<table class="screener_table"><tr><th>No.</th></tr><tr><td>1</td></tr></table>',
        "html.parser",
    )
    assert _parse_rows(soup) == []


def test_parse_rows_no_table_returns_empty():
    soup = BeautifulSoup("<div>no table here</div>", "html.parser")
    assert _parse_rows(soup) == []


def test_page_count_single_page_without_page_select():
    soup = _table_soup(_row_html("AAZIO"))
    assert _page_count(soup) == 1


def test_page_count_no_results():
    soup = BeautifulSoup("<div>No ticker found.</div>", "html.parser")
    assert _page_count(soup) == 0


def test_page_count_multi_page():
    html = (
        '<select id="pageSelect"><option>1</option><option>2</option><option>3</option></select>'
    )
    soup = BeautifulSoup(html, "html.parser")
    assert _page_count(soup) == 3
