import pandas as pd
import pytest

from screeners.news_movers import _rows_from_df


def _make_df():
    # Ticker values simulate finvizfinance's duplicated-leading-character bug
    # (e.g. real ticker "HOWL" comes back from the scraper as "HHOWL"). Price,
    # Volume, Avg Volume and Rel Volume come back as floats (finvizfinance
    # number-converts NUMBER_COL cells), but "Change %" stays a raw percent
    # string since finvizfinance's NUMBER_COL entry is "Change", not "Change %".
    # Rel Volume order deliberately differs from Change % order so sorting by
    # the wrong column would be caught. All three clear the $300M dollar
    # volume (Price * Volume) highlight threshold.
    return pd.DataFrame({
        "Ticker":      ["HHOWL", "MMRNA", "GGRML"],
        "Price":       [10.0, 20.0, 15.0],
        "Change %":    ["102.57%", "8.86%", "22.11%"],
        "Volume":      [100_000_000.0, 50_000_000.0, 80_000_000.0],
        "Avg Volume":  [12_000_000.0, 30_000_000.0, 5_000_000.0],
        "Rel Volume":  [3.1, 4.2, 3.8],
    })


def test_rows_from_df_fixes_ticker_and_formats_fields():
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
        "Ticker":     ["AAAA", "BBBB"],
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
        "Ticker":     ["AAAA"],
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
        "Ticker":     ["TT0"],
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
        "Ticker":     ["TT0"],
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
