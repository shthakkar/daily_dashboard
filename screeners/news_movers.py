import math
import re
import time
from datetime import date

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .helpers import _FINVIZ_UA, _finviz_filter_param, fix_finviz_tickers, now_utc_iso

_FILTERS = {"Country": "USA", "Relative Volume": "Over 3", "Current Volume": "Over 5M"}

# Custom-screener column set: No., Ticker, Price, Change, Volume, Avg Volume,
# Rel Volume (same columns as before, now addressed by the grid's column ids).
_COLUMNS_PARAM = "0,1,65,66,67,63,64"
_NEWS_FILTER_CODE = "news_date_today"
_PAGE_SIZE = 20

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


def _parse_number(v) -> float | None:
    # `_fetch` reads Price/Volume/Avg Volume/Rel Volume as raw cell text
    # (see its docstring for why), so these arrive as Finviz's display
    # strings -- plain ("23.25"), comma-grouped ("11,917,022"), or
    # K/M/B-suffixed ("512.57K") -- rather than pre-converted floats.
    s = str(v).strip().replace(",", "")
    if s in ("", "nan", "-", "None"):
        return None
    suffix_mult = {"K": 1e3, "M": 1e6, "B": 1e9}
    try:
        if s[-1] in suffix_mult:
            return float(s[:-1]) * suffix_mult[s[-1]]
        return float(s)
    except (ValueError, IndexError):
        return None


def _rows_from_df(df) -> list[dict]:
    if df is None or df.empty:
        return []
    # NaN Price/Volume produces a NaN dollar volume, which `>` evaluates to
    # False for -- those rows are just left unhighlighted, not excluded.
    df = df.assign(_dollar_volume=df["Price"] * df["Volume"])
    df = df.sort_values("Rel Volume", ascending=False, na_position="last")
    return [
        {
            "ticker":            str(row["Ticker"]),
            "price":             _fmt_price(row["Price"]),
            "change":            _fmt_pct(row["Change %"]),
            "volume":            _fmt_vol(row["Volume"]),
            "avg_volume":        _fmt_vol(row["Avg Volume"]),
            "rel_volume":        _fmt_relvol(row["Rel Volume"]),
            "high_dollar_volume": bool(row["_dollar_volume"] > _HIGH_DOLLAR_VOLUME),
        }
        for _, row in df.iterrows()
    ]


# Grid column ids in the custom (v=151) table, in display order.
_GRID_COLUMNS = ["row", "ticker", "price", "change", "volume", "averageVolume", "relativeVolume"]


def _parse_rows(html: str) -> list[dict]:
    """Parse one page of Finviz's new div-grid screener markup.

    Each data cell is a `div.fv-table_cell[role=gridcell][data-column-id]`;
    the ticker cell carries a `data-ticker` attribute with the clean symbol
    (the cell *text* still has the old avatar-duplication quirk, so the
    attribute is the only trustworthy source for tickers).
    """
    soup = BeautifulSoup(html, "html.parser")
    cells = soup.find_all("div", class_="fv-table_cell", attrs={"role": "gridcell"})
    records = []
    row: dict = {}
    for cell in cells:
        col = cell.get("data-column-id")
        if col not in _GRID_COLUMNS:
            continue
        if col == "row":
            if row:
                records.append(row)
            row = {}
        if col == "ticker":
            row["Ticker"] = cell.get("data-ticker") or cell.get_text(strip=True)
            row["_from_text"] = not cell.get("data-ticker")
        elif col == "price":
            row["Price"] = _parse_number(cell.get_text(strip=True))
        elif col == "change":
            row["Change %"] = cell.get_text(strip=True)
        elif col == "volume":
            row["Volume"] = _parse_number(cell.get_text(strip=True))
        elif col == "averageVolume":
            row["Avg Volume"] = _parse_number(cell.get_text(strip=True))
        elif col == "relativeVolume":
            row["Rel Volume"] = _parse_number(cell.get_text(strip=True))
    if row:
        records.append(row)
    # Repair scraped-text tickers only (data-attribute ones are already clean).
    text_idx = [i for i, r in enumerate(records) if r.pop("_from_text", False)]
    if text_idx:
        fixed = fix_finviz_tickers([records[i]["Ticker"] for i in text_idx])
        for i, t in zip(text_idx, fixed):
            records[i]["Ticker"] = t
    return records


def _fetch() -> pd.DataFrame:
    """Fetch all pages of the custom screener (USA, rel vol > 3x, volume > 5M,
    news today) and return the raw records as a DataFrame.

    Finviz redesigned the screener in Oct 2026 (JS-rendered div grid, no
    server-side table), breaking finvizfinance's scraper -- this hits the
    screener URL directly and parses the new grid markup.
    """
    f = _finviz_filter_param(_FILTERS) + "," + _NEWS_FILTER_CODE
    session = requests.Session()
    session.headers.update({"User-Agent": _FINVIZ_UA})
    records: list[dict] = []
    total = None
    r = 1
    while True:
        resp = session.get(
            "https://finviz.com/screener.ashx",
            params={"v": "151", "f": f, "c": _COLUMNS_PARAM, "r": r},
            timeout=30,
        )
        resp.raise_for_status()
        html = resp.text
        if total is None:
            m = re.search(r'"totalCount"\s*:\s*(\d+)', html)
            total = int(m.group(1)) if m else 0
        page_records = _parse_rows(html)
        records.extend(page_records)
        if len(page_records) < _PAGE_SIZE or (total and len(records) >= total):
            break
        r += _PAGE_SIZE
        time.sleep(1)
    return pd.DataFrame(records)


def run() -> dict:
    stocks = _rows_from_df(_fetch())
    return {"date": date.today().isoformat(), "updated_at": now_utc_iso(), "stocks": stocks}
