import math
from datetime import date

import pandas as pd
from finvizfinance.screener.custom import Custom
from finvizfinance.util import web_scrap

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


_PAGE_SIZE = 20  # rows per page -- matches finvizfinance's Base.size


def _parse_rows(soup) -> list[dict]:
    table = soup.find("table", class_="screener_table")
    if table is None:
        return []
    records = []
    for row in table.find_all("tr")[1:]:
        cols = row.find_all("td")
        if len(cols) < 7:
            continue
        # cols[0] is the row-number column; cols[1] is Ticker. Fall back to
        # finvizfinance's strip-one-character fix if Finviz ever drops the
        # data attribute, rather than silently dropping the row.
        ticker = cols[1].get("data-boxover-ticker") or fix_finviz_ticker(cols[1].text)
        records.append({
            "Ticker":     ticker,
            "Price":      _parse_number(cols[2].text),
            "Change %":   cols[3].text,
            "Volume":     _parse_number(cols[4].text),
            "Avg Volume": _parse_number(cols[5].text),
            "Rel Volume": _parse_number(cols[6].text),
        })
    return records


def _page_count(soup) -> int:
    try:
        return len(soup.find(id="pageSelect").find_all("option"))
    except AttributeError:
        return 1 if soup.find("table", class_="screener_table") else 0


def _fetch() -> pd.DataFrame:
    """Builds the filtered request via finvizfinance's `Custom` screener, but
    parses the response HTML directly instead of using its `screener_view` --
    that method reads each cell's full text, and Finviz's ticker cell renders
    an avatar-logo link (whose fallback text is normally the ticker's first
    letter, for when the logo image doesn't load) immediately before the real
    ticker link, so the concatenated text comes back as e.g. "CCRM" for
    Salesforce. finvizfinance's own fix assumes that fallback is always
    exactly one character and strips it accordingly, which silently mangles
    any row where Finviz's fallback text is longer (observed in production:
    a whole batch of rows came back missing an extra leading letter, e.g.
    "RM" instead of "CRM"). Every ticker cell also carries a
    `data-boxover-ticker` attribute with the plain, un-decorated symbol --
    reading that directly sidesteps the guessing game entirely.

    Pages through all results (matching finvizfinance's own 20-rows-per-page
    behavior) rather than silently capping at the first page.
    """
    screen = Custom()
    screen.set_filter(filters_dict=_FILTERS)
    # finvizfinance's filter_dict has no entry for Finviz's "Latest News" filter
    # category, so `set_filter` can't express it -- append Finviz's raw filter
    # code for "Latest News: Today" directly onto the query string it built.
    screen.request_params["f"] += ",news_date_today"
    screen._parse_columns(_COLUMNS)

    soup = web_scrap(screen.url, screen.request_params)
    records = _parse_rows(soup)
    for page in range(1, _page_count(soup)):
        screen.request_params["r"] = page * _PAGE_SIZE + 1
        records.extend(_parse_rows(web_scrap(screen.url, screen.request_params)))
    return pd.DataFrame(records)


def run() -> dict:
    stocks = _rows_from_df(_fetch())
    return {"date": date.today().isoformat(), "updated_at": now_utc_iso(), "stocks": stocks}
