import numpy as np
import pandas as pd
import pytest

from screeners.helpers import compute_momentum


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
