import pandas as pd
import pytest

from screeners.parabolic_short import _rows_from_df


def test_rows_from_df_returns_top_5():
    # Ticker values simulate finvizfinance's duplicated-leading-character bug
    # (e.g. real ticker "T0" comes back from the scraper as "TT0").
    df = pd.DataFrame({
        "Ticker":     [f"T{i}"[0] + f"T{i}" for i in range(10)],
        "Perf Week":  [f"+{10 - i}%" for i in range(10)],
        "Perf Month": [f"+{(10 - i) * 2}%" for i in range(10)],
    })
    rows = _rows_from_df(df)
    assert len(rows) == 5
    assert rows[0]["ticker"] == "T0"
    assert rows[0]["perf_week"] == "+10%"
    assert rows[0]["perf_month"] == "+20%"


def test_rows_from_df_none_returns_empty():
    assert _rows_from_df(None) == []


def test_rows_from_df_empty_df_returns_empty():
    assert _rows_from_df(pd.DataFrame()) == []


def test_rows_from_df_fewer_than_5_rows():
    df = pd.DataFrame({
        "Ticker": ["AA", "BB"],
        "Perf Week": ["+5%", "+3%"],
        "Perf Month": ["+10%", "+6%"],
    })
    rows = _rows_from_df(df)
    assert len(rows) == 2
    assert rows[0]["ticker"] == "A"
    assert rows[1]["ticker"] == "B"
