import numpy as np
import pandas as pd
import pytest

from screeners.qullamaggie import _compute_tightness_score, _rate_tightness, run


def _make_price_df(tickers, n_days=200):
    dates = pd.date_range("2025-01-01", periods=n_days)
    np.random.seed(42)
    return pd.DataFrame(
        {t: 100 * (1 + np.random.randn(n_days) * 0.01).cumprod() for t in tickers},
        index=dates,
    )


def _make_momentum(tickers, avg_rank=0.95):
    return pd.DataFrame(
        {"1M": 0.05, "3M": 0.10, "6M": 0.15, "9M": 0.20, "avg_rank": avg_rank},
        index=tickers,
    )


# --- _compute_tightness_score ---

def test_tightness_score_perfect_alignment_is_10():
    score = _compute_tightness_score(100.0, 100.0, 100.0, 100.0)
    assert score == 10.0


def test_tightness_score_clamps_to_1_at_min():
    score = _compute_tightness_score(100.0, 130.0, 70.0, 160.0)
    assert score == 1.0


def test_tightness_score_within_bounds():
    score = _compute_tightness_score(100.0, 101.0, 100.5, 99.0)
    assert 1.0 <= score <= 10.0


def test_tightness_score_tighter_mas_give_higher_score():
    tight = _compute_tightness_score(100.0, 100.1, 100.0, 99.9)
    wide  = _compute_tightness_score(100.0, 105.0, 100.0, 95.0)
    assert tight > wide


# --- _rate_tightness ---

def test_rate_tightness_extremely_tight():
    assert _rate_tightness(9.0) == "Extremely Tight"


def test_rate_tightness_very_tight():
    assert _rate_tightness(7.5) == "Very Tight"


def test_rate_tightness_tight():
    assert _rate_tightness(6.0) == "Tight"


def test_rate_tightness_medium():
    assert _rate_tightness(4.5) == "Medium"


def test_rate_tightness_wide():
    assert _rate_tightness(2.0) == "Wide"


# --- run ---

def test_run_returns_expected_keys():
    tickers = [f"T{i:02d}" for i in range(5)]
    data = _make_price_df(tickers)
    momentum = _make_momentum(tickers, avg_rank=0.95)
    result = run(data, momentum)
    assert "date" in result
    assert "stocks" in result


def test_run_stock_has_required_fields():
    tickers = ["AA"]
    data = _make_price_df(tickers)
    momentum = _make_momentum(tickers, avg_rank=0.95)
    result = run(data, momentum)
    if result["stocks"]:
        s = result["stocks"][0]
        assert "ticker" in s
        assert "tightness" in s
        assert "rating" in s
        assert "close" in s
        assert "avg_rank" in s
        assert 1.0 <= s["tightness"] <= 10.0


def test_run_filters_below_92nd_percentile():
    tickers = [f"T{i:02d}" for i in range(5)]
    data = _make_price_df(tickers)
    momentum = _make_momentum(tickers, avg_rank=0.5)  # below 0.92 threshold
    result = run(data, momentum)
    assert result["stocks"] == []


def test_run_sorted_by_tightness_descending():
    tickers = [f"T{i:02d}" for i in range(10)]
    data = _make_price_df(tickers)
    momentum = _make_momentum(tickers, avg_rank=0.95)
    result = run(data, momentum)
    scores = [s["tightness"] for s in result["stocks"]]
    assert scores == sorted(scores, reverse=True)
