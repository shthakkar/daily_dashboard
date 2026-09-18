"""Capitulation-fade screener: the automated technical leg of the Variable Framework.

For each ticker it computes, from daily OHLCV:
  - consecutive closes in the same direction (Variable 2)
  - Bollinger Band (20, 2sd) extension, as fraction of bandwidth (Variable 3)
  - distance from the 20-day SMA, in percent (Variable 3)
  - relative volume vs 20-day average (Variable 5)
  - 3-day rate of change + acceleration of log returns (Variable 1)
  - ATR(14)/ATR(50) expansion ratio (Variable 7)

Each direction (short = parabolic up move to fade, long = waterfall down move
to fade) is scored 0-6 on how many conditions fire. Candidates are rows with
score >= MIN_SCORE.

The qualitative variables (fresh catalyst, multiple legs, sentiment,
forced liquidation) cannot be automated and must be checked by hand per
candidate.
"""
from datetime import date

import numpy as np
import pandas as pd

from .helpers import now_utc_iso

MIN_BARS = 60
MIN_CONSEC = 3
MIN_EXT = 0.25       # close beyond the band by >= 25% of bandwidth
MIN_DIST_SMA = 8.0   # percent from 20-day SMA
MIN_RVOL = 3.0       # volume vs 20-day average
MIN_ROC3 = 5.0       # percent move over 3 days
MIN_ATR_RATIO = 1.3  # ATR(14) vs ATR(50)
MIN_SCORE = 4        # candidate threshold


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _consec(bool_s: pd.Series) -> pd.Series:
    """Length of the consecutive True streak ending at each bar."""
    return bool_s.groupby((~bool_s).cumsum()).cumsum()


def _metrics(ticker: str, df: pd.DataFrame) -> dict | None:
    """Per-ticker metric dict for the latest bar, or None if not enough history."""
    df = df.dropna(subset=["Close"])
    if len(df) < MIN_BARS:
        return None
    c, v = df["Close"], df["Volume"]
    sma20 = c.rolling(20).mean()
    sd20 = c.rolling(20).std()
    upper, lower = sma20 + 2 * sd20, sma20 - 2 * sd20
    bw = (upper - lower).replace(0, np.nan)
    ext_up = (c - upper) / bw
    ext_dn = (lower - c) / bw
    dist = (c / sma20 - 1) * 100
    rvol = v / v.rolling(20).mean()
    roc3 = (c / c.shift(3) - 1) * 100
    lr = np.log(c / c.shift(1))
    accel = (lr.rolling(3).mean() - lr.rolling(10).mean()) * 100  # pp per day
    atr_ratio = _atr(df, 14) / _atr(df, 50)
    cu = _consec(c > c.shift(1))
    cd = _consec(c < c.shift(1))

    def g(s: pd.Series) -> float:
        x = s.iloc[-1]
        return float(x) if pd.notna(x) else np.nan

    last = df.index[-1]
    return {
        "ticker": ticker,
        "date": last.date().isoformat() if hasattr(last, "date") else str(last),
        "close": round(g(c), 2),
        "consec_up": int(g(cu)),
        "consec_dn": int(g(cd)),
        "ext_up": round(g(ext_up), 3),
        "ext_dn": round(g(ext_dn), 3),
        "dist_sma": round(g(dist), 2),
        "rvol": round(g(rvol), 2),
        "roc3": round(g(roc3), 2),
        "accel": round(g(accel), 3),
        "atr_ratio": round(g(atr_ratio), 2),
    }


def _score(m: dict, direction: str) -> tuple[int, list[str]]:
    """Return (score, fired_conditions) for a metric row."""
    if direction == "short":  # parabolic UP move -> fade short
        conds = [
            ("consec>=3", m["consec_up"] >= MIN_CONSEC),
            ("outside_band", m["ext_up"] >= MIN_EXT),
            ("stretched_sma", m["dist_sma"] >= MIN_DIST_SMA),
            ("rvol>=3", m["rvol"] >= MIN_RVOL),
            ("accel_up", m["roc3"] >= MIN_ROC3 and m["accel"] > 0),
            ("atr_expand", m["atr_ratio"] >= MIN_ATR_RATIO),
        ]
    else:  # waterfall DOWN move -> fade long
        conds = [
            ("consec>=3", m["consec_dn"] >= MIN_CONSEC),
            ("outside_band", m["ext_dn"] >= MIN_EXT),
            ("stretched_sma", m["dist_sma"] <= -MIN_DIST_SMA),
            ("rvol>=3", m["rvol"] >= MIN_RVOL),
            ("accel_dn", m["roc3"] <= -MIN_ROC3 and m["accel"] < 0),
            ("atr_expand", m["atr_ratio"] >= MIN_ATR_RATIO),
        ]
    fired = [name for name, ok in conds if ok]
    return len(fired), fired


def _fmt_pct(v: float) -> str:
    return f"{v:+.1f}%"


def run(ohlcv: dict[str, pd.DataFrame]) -> dict:
    """Screen the {ticker: OHLCV DataFrame} universe; returns the dashboard JSON."""
    stocks = []
    for ticker, df in ohlcv.items():
        m = _metrics(ticker, df)
        if m is None or any(
            pd.isna(m[k]) for k in ("ext_up", "dist_sma", "rvol", "roc3", "accel", "atr_ratio")
        ):
            continue
        for direction in ("short", "long"):
            s, _fired = _score(m, direction)
            if s >= MIN_SCORE:
                stocks.append({
                    "ticker": ticker,
                    "setup": "Fade Short" if direction == "short" else "Fade Long",
                    "direction": direction,
                    "score": f"{s}/6",
                    "close": m["close"],
                    "stretch": _fmt_pct(m["dist_sma"]),
                    "rvol": f"{m['rvol']:.1f}x",
                    "roc3": _fmt_pct(m["roc3"]),
                    "_sort": (s, m["ext_up"] if direction == "short" else m["ext_dn"]),
                })
    stocks.sort(key=lambda r: r["_sort"], reverse=True)
    for r in stocks:
        del r["_sort"]
    return {"date": date.today().isoformat(), "updated_at": now_utc_iso(), "stocks": stocks}
