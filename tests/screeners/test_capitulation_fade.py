import numpy as np
import pandas as pd

from screeners.capitulation_fade import MIN_SCORE, _metrics, _score, run


def _frame(close, volume):
    """Build an OHLCV frame from close/volume arrays (simple synthetic bars)."""
    close = np.asarray(close, dtype=float)
    volume = np.asarray(volume, dtype=float)
    n = len(close)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * 1.005
    low = np.minimum(open_, close) * 0.995
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}
    )


def _parabolic_frame(n=80, base=100.0, seed=3):
    """Flat base for 75 bars, then a 5-day volume-backed vertical run."""
    rng = np.random.default_rng(seed)
    close = np.full(n, base, dtype=float)
    close += np.cumsum(rng.normal(0, 0.15, n))  # small wiggle
    pops = [1.18, 1.20, 1.18, 1.22, 1.18]
    for i, p in enumerate(pops):
        close[n - 5 + i] = close[n - 6 + i] * p
    volume = np.full(n, 1_000_000.0)
    volume[-5:] = 10_000_000.0
    return _frame(close, volume)


def _flat_frame(n=80, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.4, n))
    volume = np.full(n, 1_000_000.0)
    return _frame(close, volume)


def test_run_returns_expected_keys():
    result = run({"AAA": _parabolic_frame()})
    assert "date" in result
    assert "updated_at" in result
    assert "stocks" in result


def test_parabolic_up_move_scores_short_candidate():
    m = _metrics("AAA", _parabolic_frame())
    s, fired = _score(m, "short")
    assert s >= MIN_SCORE, f"expected >= {MIN_SCORE}, got {s} ({fired})"
    assert s == 6, f"expected a full 6/6 on the synthetic blowoff, got {s} ({fired})"


def test_parabolic_up_move_is_not_a_long_candidate():
    m = _metrics("AAA", _parabolic_frame())
    s, _ = _score(m, "long")
    assert s < MIN_SCORE


def test_flat_market_produces_no_candidates():
    result = run({"AAA": _flat_frame(), "BBB": _flat_frame(seed=9)})
    assert result["stocks"] == []


def test_run_candidate_has_required_fields():
    result = run({"AAA": _parabolic_frame()})
    assert len(result["stocks"]) == 1
    s = result["stocks"][0]
    assert s["ticker"] == "AAA"
    assert s["setup"] == "Fade Short"
    assert s["direction"] == "short"
    assert s["score"] == "6/6"
    assert isinstance(s["close"], float)
    assert s["stretch"].endswith("%")
    assert s["rvol"].endswith("x")
    assert s["roc3"].endswith("%")


def test_run_skips_short_history():
    result = run({"AAA": _frame([100.0] * 30, [1_000_000.0] * 30)})
    assert result["stocks"] == []


def test_run_sorted_by_score_then_extension():
    strong = _parabolic_frame(seed=3)
    weaker = _parabolic_frame(seed=11)  # different wiggle, may score lower/equal
    result = run({"AAA": strong, "BBB": weaker})
    scores = [int(s["score"].split("/")[0]) for s in result["stocks"]]
    assert scores == sorted(scores, reverse=True)
