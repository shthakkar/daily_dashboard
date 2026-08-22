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
    # the wrong column would be caught.
    return pd.DataFrame({
        "Ticker":      ["HHOWL", "MMRNA", "GGRML"],
        "Price":       [0.87, 145.13, 0.20],
        "Change %":    ["102.57%", "8.86%", "22.11%"],
        "Volume":      [296734530.0, 87316065.0, 78359307.0],
        "Avg Volume":  [12000000.0, 30000000.0, 5000000.0],
        "Rel Volume":  [3.1, 4.2, 3.8],
    })


def test_rows_from_df_fixes_ticker_and_formats_fields():
    rows = _rows_from_df(_make_df())
    top = next(r for r in rows if r["ticker"] == "HOWL")
    assert top["price"] == "$0.87"
    assert top["change"] == "+102.57%"
    assert top["volume"] == "296.7M"
    assert top["avg_volume"] == "12.0M"
    assert top["rel_volume"] == "3.1x"


def test_rows_from_df_sorted_by_rel_volume_descending():
    rows = _rows_from_df(_make_df())
    assert [r["ticker"] for r in rows] == ["MRNA", "GRML", "HOWL"]


def test_rows_from_df_none_returns_empty():
    assert _rows_from_df(None) == []


def test_rows_from_df_empty_df_returns_empty():
    assert _rows_from_df(pd.DataFrame()) == []


def test_rows_from_df_handles_nan():
    df = pd.DataFrame({
        "Ticker":     ["TT0"],
        "Price":      [float("nan")],
        "Change %":   [float("nan")],
        "Volume":     [float("nan")],
        "Avg Volume": [float("nan")],
        "Rel Volume": [float("nan")],
    })
    rows = _rows_from_df(df)
    assert rows[0]["ticker"] == "T0"
    assert rows[0]["price"] == "N/A"
    assert rows[0]["change"] == "N/A"
    assert rows[0]["volume"] == "N/A"
    assert rows[0]["avg_volume"] == "N/A"
    assert rows[0]["rel_volume"] == "N/A"
