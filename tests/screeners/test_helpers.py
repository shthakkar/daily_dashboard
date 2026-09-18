import numpy as np
import pandas as pd
import pytest

from screeners.helpers import _drop_trailing_empty_row, compute_momentum, fix_finviz_tickers, now_utc_iso


# --- fix_finviz_tickers ---
# The scraper sometimes doubles the leading letter ("ZYME" -> "ZZYME"); the
# helper strips only when a majority of the scrape shows the doubling, and
# leaves clean scrapes untouched.

def test_fix_finviz_tickers_strips_when_majority_doubled():
    # In a duplicated scrape even a clean-looking "AAPL" is treated as doubled.
    assert fix_finviz_tickers(["ZZYME", "AAAPL", "MMMM", "AAPL"]) == ["ZYME", "AAPL", "MMM", "APL"]


def test_fix_finviz_tickers_leaves_clean_scrape_untouched():
    # Only a couple of real double-letter tickers (AA, AAOI) -- no stripping.
    assert fix_finviz_tickers(["AAOI", "AAON", "AAPL", "ABBV", "ABNB", "ABT"]) == ["AAOI", "AAON", "AAPL", "ABBV", "ABNB", "ABT"]


def test_fix_finviz_tickers_empty_list():
    assert fix_finviz_tickers([]) == []


def test_fix_finviz_tickers_single_char_tickers_kept():
    assert fix_finviz_tickers(["A", "F", "T"]) == ["A", "F", "T"]


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
# In practice the row is rarely 100% NaN (a handful of tickers often already
# carry a value), so the drop uses a majority threshold rather than requiring
# every column to be NaN.

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


def test_drop_trailing_empty_row_removes_majority_nan_last_row():
    # 8 of 10 tickers missing "today" -- realistic pre-market shape, not
    # literally every column NaN.
    cols = {f"T{i}": [1.0, 2.0, np.nan] for i in range(8)}
    cols.update({f"T{i}": [1.0, 2.0, 3.0] for i in range(8, 10)})
    close = pd.DataFrame(cols)
    high = close * 1.01
    close_out, high_out = _drop_trailing_empty_row(close, high)
    assert len(close_out) == 2
    assert len(high_out) == 2


def test_drop_trailing_empty_row_keeps_minority_nan_last_row():
    # Only 2 of 10 tickers missing "today" -- isolated per-ticker gaps, not
    # a pre-market placeholder; must not be stripped.
    cols = {f"T{i}": [1.0, 2.0, 3.0] for i in range(8)}
    cols.update({f"T{i}": [1.0, 2.0, np.nan] for i in range(8, 10)})
    close = pd.DataFrame(cols)
    high = close * 1.01
    close_out, _ = _drop_trailing_empty_row(close, high)
    assert len(close_out) == 3


# --- now_utc_iso ---

def test_now_utc_iso_is_parseable_and_has_utc_offset():
    from datetime import datetime
    result = now_utc_iso()
    parsed = datetime.fromisoformat(result)
    assert parsed.utcoffset().total_seconds() == 0
