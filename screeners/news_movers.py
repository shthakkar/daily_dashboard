import math
from datetime import date

import pandas as pd
from finvizfinance.screener.custom import Custom

from .helpers import fix_finviz_ticker, now_utc_iso

_FILTERS = {"Country": "USA", "Relative Volume": "Over 3", "Current Volume": "Over 5M"}

# No. (dropped by finvizfinance), Ticker, Price, Change, Volume, Avg Volume, Rel Volume
_COLUMNS = [0, 1, 65, 66, 67, 63, 64]

# Finviz has no dollar-volume filter of its own. Rather than excluding rows
# below this, it's surfaced as a `high_dollar_volume` flag so the UI can
# highlight the more-liquid names while still showing every match.
_HIGH_DOLLAR_VOLUME = 300_000_000


def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _fmt_price(v) -> str:
    f = _safe_float(v)
    return "N/A" if f is None else f"${f:.2f}"


def _parse_pct(v) -> float | None:
    # finvizfinance's own NUMBER_COL list has an entry for "Change" but the
    # live page's header text is actually "Change %", so the mismatch means
    # this column never gets auto-converted -- it arrives as a raw "9.22%"
    # string (already in percentage units, not a 0-1 fraction) rather than
    # a float, so it needs its own parsing instead of `_safe_float`.
    s = str(v).strip()
    if s in ("", "nan", "-", "None"):
        return None
    try:
        return float(s.rstrip("%"))
    except ValueError:
        return None


def _fmt_pct(v) -> str:
    f = _parse_pct(v)
    return "N/A" if f is None else f"{f:+.2f}%"


def _fmt_vol(v) -> str:
    f = _safe_float(v)
    if f is None:
        return "N/A"
    if f >= 1e9:
        return f"{f / 1e9:.1f}B"
    if f >= 1e6:
        return f"{f / 1e6:.1f}M"
    if f >= 1e3:
        return f"{f / 1e3:.1f}K"
    return f"{f:.0f}"


def _fmt_relvol(v) -> str:
    f = _safe_float(v)
    return "N/A" if f is None else f"{f:.1f}x"


def _rows_from_df(df) -> list[dict]:
    if df is None or df.empty:
        return []
    # NaN Price/Volume produces a NaN dollar volume, which `>` evaluates to
    # False for -- those rows are just left unhighlighted, not excluded.
    df = df.assign(_dollar_volume=df["Price"] * df["Volume"])
    df = df.sort_values("Rel Volume", ascending=False, na_position="last")
    return [
        {
            "ticker":            fix_finviz_ticker(str(row["Ticker"])),
            "price":             _fmt_price(row["Price"]),
            "change":            _fmt_pct(row["Change %"]),
            "volume":            _fmt_vol(row["Volume"]),
            "avg_volume":        _fmt_vol(row["Avg Volume"]),
            "rel_volume":        _fmt_relvol(row["Rel Volume"]),
            "high_dollar_volume": bool(row["_dollar_volume"] > _HIGH_DOLLAR_VOLUME),
        }
        for _, row in df.iterrows()
    ]


def _fetch() -> pd.DataFrame:
    screen = Custom()
    screen.set_filter(filters_dict=_FILTERS)
    # finvizfinance's filter_dict has no entry for Finviz's "Latest News" filter
    # category, so `set_filter` can't express it -- append Finviz's raw filter
    # code for "Latest News: Today" directly onto the query string it built.
    screen.request_params["f"] += ",news_date_today"
    return screen.screener_view(columns=_COLUMNS, verbose=0)


def run() -> dict:
    stocks = _rows_from_df(_fetch())
    return {"date": date.today().isoformat(), "updated_at": now_utc_iso(), "stocks": stocks}
