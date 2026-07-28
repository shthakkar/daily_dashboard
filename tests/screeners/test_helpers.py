import numpy as np
import pandas as pd
import pytest

from screeners.helpers import _drop_trailing_empty_row, compute_momentum, fix_finviz_ticker


# --- fix_finviz_ticker ---
# finvizfinance's HTML scraper concatenates a one-letter avatar span with the
# real ticker link text (e.g. "Z" + "ZYME" -> "ZZYME"); these tests use the
# corrupted (doubled-leading-character) form as input, matching what the
# scraper actually returns.

def test_fix_finviz_ticker_strips_duplicated_leading_char():
    assert fix_finviz_ticker("ZZYME") == "ZYME"


def test_fix_finviz_ticker_single_char_real_ticker():
    assert fix_finviz_ticker("FF") == "F"


def test_fix_finviz_ticker_naturally_double_leading_letter():
    # Real ticker "MMM" -> corrupted "MMMM"; stripping one char still recovers it.
    assert fix_finviz_ticker("MMMM") == "MMM"


def test_fix_finviz_ticker_hyphenated_ticker():
    assert fix_finviz_ticker("BBRK-B") == "BRK-B"


def _make_price_df(tickers, n_days=200):
    dates = pd.date_range("2025-01-01", periods=n_days)
    np.random.seed(42)
    return pd.DataFrame(
        {t: 100 * (1 + np.random.randn(n_days) * 0.01).cumprod() for t in tickers},
        index=dates,
    )


def test_compute_momentum_columns():
    data = _make_price_df(["AAA", "BBB"])
    result = compute_momentum(data)
    assert list(result.columns) == ["1M", "3M", "6M", "9M", "avg_rank"]


def test_compute_momentum_index_is_tickers():
    data = _make_price_df(["AAA", "BBB"])
    result = compute_momentum(data)
    assert set(result.index) == {"AAA", "BBB"}


def test_compute_momentum_avg_rank_between_0_and_1():
    data = _make_price_df(["AAA", "BBB", "CCC"])
    result = compute_momentum(data)
    assert result["avg_rank"].between(0, 1).all()


def test_compute_momentum_higher_return_gets_higher_rank():
    # AAA doubles each period, BBB stays flat — AAA should rank higher
    n = 200
    dates = pd.date_range("2025-01-01", periods=n)
    data = pd.DataFrame(
        {
            "AAA": [100 * (1.001**i) for i in range(n)],
            "BBB": [100.0] * n,
        },
        index=dates,
    )
    result = compute_momentum(data)
    assert result.loc["AAA", "avg_rank"] > result.loc["BBB", "avg_rank"]


def test_compute_momentum_raises_on_short_history():
    data = _make_price_df(["AAA"], n_days=100)
    with pytest.raises(ValueError, match="too short"):
        compute_momentum(data)


# --- _drop_trailing_empty_row ---
# Yahoo appends a placeholder row for "today" with no close yet before the
# market opens; this must be stripped or every .iloc[-1] downstream sees NaN.

def test_drop_trailing_empty_row_removes_fully_nan_last_row():
    close = pd.DataFrame({"AAA": [1.0, 2.0, np.nan], "BBB": [3.0, 4.0, np.nan]})
    high = pd.DataFrame({"AAA": [1.5, 2.5, np.nan], "BBB": [3.5, 4.5, np.nan]})
    close_out, high_out = _drop_trailing_empty_row(close, high)
    assert len(close_out) == 2
    assert len(high_out) == 2


def test_drop_trailing_empty_row_removes_multiple_trailing_nan_rows():
    close = pd.DataFrame({"AAA": [1.0, 2.0, np.nan, np.nan]})
    high = pd.DataFrame({"AAA": [1.5, 2.5, np.nan, np.nan]})
    close_out, _ = _drop_trailing_empty_row(close, high)
    assert len(close_out) == 2


def test_drop_trailing_empty_row_keeps_partial_nan_last_row():
    # Only some tickers missing the last day (real data gap, not a
    # universal placeholder) -- must not be stripped.
    close = pd.DataFrame({"AAA": [1.0, 2.0, 3.0], "BBB": [3.0, 4.0, np.nan]})
    high = pd.DataFrame({"AAA": [1.5, 2.5, 3.5], "BBB": [3.5, 4.5, np.nan]})
    close_out, high_out = _drop_trailing_empty_row(close, high)
    assert len(close_out) == 3
    assert len(high_out) == 3


def test_drop_trailing_empty_row_handles_empty_input():
    close = pd.DataFrame()
    high = pd.DataFrame()
    close_out, high_out = _drop_trailing_empty_row(close, high)
    assert close_out.empty
    assert high_out.empty
