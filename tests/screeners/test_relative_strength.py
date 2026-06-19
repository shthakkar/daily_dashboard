import numpy as np
import pandas as pd
import pytest

from screeners.relative_strength import run


def _make_momentum(n=100, seed=0):
    np.random.seed(seed)
    tickers = [f"T{i:03d}" for i in range(n)]
    df = pd.DataFrame(
        {
            "1M": np.random.randn(n) * 0.1,
            "3M": np.random.randn(n) * 0.15,
            "6M": np.random.randn(n) * 0.2,
            "9M": np.random.randn(n) * 0.25,
        },
        index=tickers,
    )
    ranks = df.rank(pct=True)
    df["avg_rank"] = ranks.mean(axis=1)
    return df


def test_run_returns_expected_keys():
    result = run(_make_momentum())
    assert "date" in result
    assert "stocks" in result


def test_run_filters_to_top_3_percent():
    # top 3% of 100 stocks = at most 3 stocks
    result = run(_make_momentum(n=100))
    assert len(result["stocks"]) <= 3


def test_run_sorted_by_avg_rank_descending():
    result = run(_make_momentum(n=100))
    ranks = [s["avg_rank"] for s in result["stocks"]]
    assert ranks == sorted(ranks, reverse=True)


def test_run_stock_has_required_fields():
    result = run(_make_momentum(n=100))
    if result["stocks"]:
        s = result["stocks"][0]
        assert "ticker" in s
        assert "avg_rank" in s
        assert "ret_1m" in s
        assert "ret_3m" in s
        assert "ret_6m" in s
        assert "ret_9m" in s


def test_run_return_strings_have_sign():
    result = run(_make_momentum(n=100))
    for s in result["stocks"]:
        assert s["ret_1m"].startswith(("+", "-"))
        assert s["ret_3m"].startswith(("+", "-"))


def test_run_empty_result_when_no_stocks_qualify():
    # All avg_rank = 0.5, below 0.97 threshold
    df = pd.DataFrame(
        {"1M": [0.0]*10, "3M": [0.0]*10, "6M": [0.0]*10, "9M": [0.0]*10, "avg_rank": [0.5]*10},
        index=[f"T{i}" for i in range(10)],
    )
    result = run(df)
    assert result["stocks"] == []
