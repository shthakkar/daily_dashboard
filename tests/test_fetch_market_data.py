import json
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from fetch_market_data import (
    classify_ema_signal,
    classify_vix_level,
    get_spy_ema_signal,
    get_vix_data,
    write_json,
)


# --- classify_ema_signal ---

def test_classify_ema_signal_bullish():
    assert classify_ema_signal(535.0, 530.0) == "bullish"


def test_classify_ema_signal_bearish():
    assert classify_ema_signal(520.0, 530.0) == "bearish"


def test_classify_ema_signal_equal_is_bearish():
    # 10EMA == 20EMA is not strictly greater, so bearish
    assert classify_ema_signal(530.0, 530.0) == "bearish"


# --- classify_vix_level ---

def test_classify_vix_level_low():
    assert classify_vix_level(12.5) == "low"


def test_classify_vix_level_low_upper_boundary():
    assert classify_vix_level(14.99) == "low"


def test_classify_vix_level_normal_lower_boundary():
    assert classify_vix_level(15.0) == "normal"


def test_classify_vix_level_normal():
    assert classify_vix_level(17.0) == "normal"


def test_classify_vix_level_normal_upper_boundary():
    assert classify_vix_level(19.99) == "normal"


def test_classify_vix_level_elevated_lower_boundary():
    assert classify_vix_level(20.0) == "elevated"


def test_classify_vix_level_elevated():
    assert classify_vix_level(25.0) == "elevated"


def test_classify_vix_level_elevated_upper_boundary():
    assert classify_vix_level(30.0) == "elevated"


def test_classify_vix_level_crisis_lower_boundary():
    assert classify_vix_level(30.01) == "crisis"


def test_classify_vix_level_crisis():
    assert classify_vix_level(35.0) == "crisis"


# --- write_json ---

def test_write_json_creates_file_with_correct_content():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "out.json")
        data = {"date": "2026-06-19", "spy_ema": "bullish", "vix": 18.4}
        write_json(data, path)
        with open(path) as f:
            result = json.load(f)
        assert result == data


def test_write_json_creates_parent_dirs():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "nested", "deep", "out.json")
        write_json({"x": 1}, path)
        assert os.path.exists(path)


# --- get_spy_ema_signal / get_vix_data ---
# Yahoo appends a placeholder row for "today" with no close yet before the
# market opens; these functions must refuse to compute against it rather
# than silently writing NaN into the dashboard.

def _make_spy_df(n_days=200, last_close_nan=False):
    dates = pd.date_range("2025-01-01", periods=n_days)
    close = 100 * (1 + np.random.RandomState(0).randn(n_days) * 0.01).cumprod()
    high = close * 1.01
    if last_close_nan:
        close[-1] = np.nan
        high[-1] = np.nan
    return pd.DataFrame({"close": close, "high": high}, index=dates)


def test_get_spy_ema_signal_raises_on_nan_last_close():
    spy = _make_spy_df(last_close_nan=True)
    with pytest.raises(ValueError, match="NaN"):
        get_spy_ema_signal(spy)


def test_get_spy_ema_signal_succeeds_with_valid_data():
    spy = _make_spy_df()
    result = get_spy_ema_signal(spy)
    assert result["spy_last_close"] == result["spy_last_close"]  # not NaN


def test_get_vix_data_raises_on_nan_last_close():
    vix = _make_spy_df(last_close_nan=True)
    with pytest.raises(ValueError, match="NaN"):
        get_vix_data(vix)


def test_get_vix_data_succeeds_with_valid_data():
    vix = _make_spy_df()
    result = get_vix_data(vix)
    assert result["vix"] == result["vix"]  # not NaN
