import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import pandas as pd
import requests
import yfinance as yf

_FINVIZ_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_FINVIZ_PAGE_SIZE = 20
# Finviz screener filter URL codes (finvizfinance's mapping, inlined so the
# universe fetch doesn't depend on that library's scraper).
_FINVIZ_FILTER_CODES = {
    "Market Cap.": {
        "prefix": "cap",
        "option": {
            "+Large (over $10bln)": "largeover",
            "Mid ($2bln to $10bln)": "mid",
        },
    },
    "Price": {"prefix": "sh_price", "option": {"Over $20": "o20"}},
    "Average Volume": {"prefix": "sh_avgvol", "option": {"Over 500K": "o500"}},
    "Country": {"prefix": "geo", "option": {"USA": "usa"}},
    "Relative Volume": {"prefix": "sh_relvol", "option": {"Over 3": "o3"}},
    "Current Volume": {"prefix": "sh_curvol", "option": {"Over 5M": "o5000"}},
}

_CHUNK_SIZE = 40
_CHUNK_DELAY_SECONDS = 2
_MAX_RETRIES = 2
_RETRY_DELAY_SECONDS = 8


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fix_finviz_tickers(tickers: list[str]) -> list[str]:
    """Undo finvizfinance's ticker-cell scraping quirk when it is present.

    Finviz sometimes renders each ticker cell as a one-letter avatar placeholder
    span (the ticker's own first letter) followed by the real ticker link, so the
    scraped text comes back with the first letter doubled ("ZYME" -> "ZZYME").
    But the markup changes over time: as of 2026-09-17 the raw text is clean
    ("AAOI", "AAPL") and stripping unconditionally mangles every symbol
    ("AAON" -> "AON", which then 404s on Yahoo -- or worse, collides with a
    different real ticker).

    The two states are easy to tell apart: in the duplicated state essentially
    every scraped ticker starts with a doubled letter, while in the clean state
    only a handful of real tickers do (AA, AAOI, ...). So strip the leading
    character only when a majority of the scrape shows the doubling.
    """
    if not tickers:
        return tickers
    doubled = sum(1 for t in tickers if len(t) >= 2 and t[0] == t[1])
    if doubled / len(tickers) > 0.5:
        print(f"Detected doubled-letter ticker scrape ({doubled}/{len(tickers)}), stripping")
        return [t[1:] if len(t) >= 2 and t[0] == t[1] else t for t in tickers]
    return tickers


def _finviz_filter_param(filters: dict) -> str:
    """Translate human-readable filter names to Finviz's `f=` URL codes."""
    codes = []
    for key, value in filters.items():
        spec = _FINVIZ_FILTER_CODES[key]
        urlcode = spec["option"][value]
        if urlcode:
            codes.append(f"{spec['prefix']}_{urlcode}")
    return ",".join(codes)


def get_finviz_tickers(filters: dict) -> list[str]:
    """Fetch ticker symbols from Finviz's screener.

    Finviz redesigned the screener page in Oct 2026: it's now a JS-rendered
    div grid with no server-side HTML table, which broke finvizfinance's
    table scraper (it returns None). This parses the new markup directly --
    each ticker cell carries a `data-ticker` attribute with the clean symbol
    (the cell *text* still has the old avatar-duplication quirk, so the
    attribute is the only trustworthy source). Pages through all results
    (20 per page via the `r=` offset) using the `totalCount` embedded in
    the page.

    Raises on failure. A loud failure keeps the dashboard on yesterday's
    data; the previous silent fallback to a handful of hardcoded tickers
    published three days of empty "No results" dashboards (Oct 17-19, 2026)
    before anyone noticed.
    """
    f = _finviz_filter_param(filters)
    tickers: list[str] = []
    total = None
    r = 1
    session = requests.Session()
    session.headers.update({"User-Agent": _FINVIZ_UA})
    while True:
        resp = session.get(
            "https://finviz.com/screener.ashx",
            params={"v": "111", "f": f, "r": r},
            timeout=30,
        )
        resp.raise_for_status()
        html = resp.text
        if total is None:
            m = re.search(r'"totalCount"\s*:\s*(\d+)', html)
            total = int(m.group(1)) if m else 0
        page = re.findall(r'data-ticker="([A-Z0-9.\-]{1,8})"', html)
        for t in page:
            if t not in tickers:
                tickers.append(t)
        if len(page) < _FINVIZ_PAGE_SIZE or (total and len(tickers) >= total):
            break
        r += _FINVIZ_PAGE_SIZE
        time.sleep(1)
    if not tickers:
        raise RuntimeError(f"Finviz screener returned no tickers for filters {filters}")
    return fix_finviz_tickers(tickers)


def get_earnings_map(days_back: int = 10) -> dict[str, str]:
    """Tickers that reported earnings in the last `days_back` days -> ISO date.

    Source: Nasdaq's earnings calendar (one request per day). Sakshar's ask
    (2026-10-23): flag earnings next to dashboard tickers instead of dropping
    them, so earnings-day names are visible before he trades them. Extended
    2026-11-11 to a 10-calendar-day window so the 6:22 pre-trade check can
    count sessions since earnings (the post-earnings filter needs up to 5
    sessions back, which spans a weekend). Tolerant per day: a day with no
    rows (weekend/holiday) is skipped, not fatal -- but if NO day returns
    rows at all, raise so the caller ships without the annotation loudly
    rather than a fake-empty one.
    """
    out: dict[str, str] = {}
    session = requests.Session()
    session.headers.update({"User-Agent": _FINVIZ_UA,
                            "Accept": "application/json"})
    any_rows = False
    for offset in range(days_back, -1, -1):
        day = date.today() - timedelta(days=offset)
        try:
            resp = session.get(
                "https://api.nasdaq.com/api/calendar/earnings",
                params={"date": day.isoformat()}, timeout=30)
            resp.raise_for_status()
            rows = (resp.json().get("data") or {}).get("rows") or []
        except Exception:  # noqa: BLE001 - one bad day must not kill the map
            continue
        if not rows:
            continue
        any_rows = True
        for row in rows:
            sym = (row.get("symbol") or "").strip()
            if sym:
                out[sym] = day.isoformat()
    if not any_rows:
        raise RuntimeError(
            f"Nasdaq earnings calendar returned no rows in the last {days_back} days")
    return out


def _sessions_since(index, event_date: str) -> int | None:
    """Sessions in `index` (a DatetimeIndex of session dates) after event_date.

    Returns None if the index is empty. 0 means the event was today (no
    session has closed since it).
    """
    if index is None or len(index) == 0:
        return None
    try:
        ev = pd.Timestamp(event_date).date()
    except (ValueError, TypeError):
        return None
    return int(sum(1 for d in index if d.date() > ev))


def _earnings_move_pct(df: pd.DataFrame, earn_date: str) -> float | None:
    """Signed % move of the earnings reaction session.

    The report can land before the open (reaction on the report date) or
    after the close (reaction the next session), and the calendar does not
    say which -- so take the larger absolute single-session move of the
    report date and the next session. Returns None when neither session has
    a close yet (reported this morning and the market has not closed).
    """
    if df is None or df.empty or "Close" not in df.columns:
        return None
    try:
        ev = pd.Timestamp(earn_date)
    except (ValueError, TypeError):
        return None
    closes = df["Close"].dropna()
    if closes.empty:
        return None
    # First session on or after the report date; if the report date is not a
    # session (weekend), the next session is the reaction session.
    after = closes.loc[closes.index >= ev]
    if after.empty:
        return None
    moves = []
    for pos in range(len(closes)):
        if closes.index[pos] < ev:
            continue
        if pos == 0:
            continue
        moves.append(float(closes.iloc[pos] / closes.iloc[pos - 1] - 1) * 100)
        if len(moves) >= 2:
            break
    if not moves:
        return None
    best = max(moves, key=abs)
    return round(best, 2)


def annotate_earnings(result: dict, earnings: dict[str, str],
                      ohlcv: dict | None = None) -> int:
    """Set earnings fields on fade rows: date, day move, sessions since.

    Mutates `result` in place; returns how many stocks were annotated.
    With `ohlcv` (the pipeline's per-ticker daily bars) each flagged row also
    gets `earnings_move_pct` (the reaction-session % move -- the larger of the
    report date and the next session, since the calendar does not say whether
    the report landed before the open or after the close) and
    `sessions_since_earnings` (sessions closed since the report). Without
    `ohlcv` it only sets the date, as before.
    """
    n = 0
    for stock in result.get("stocks", []):
        d = earnings.get(stock.get("ticker"))
        if d:
            stock["earnings_date"] = d
            if ohlcv is not None:
                df = ohlcv.get(stock["ticker"])
                stock["earnings_move_pct"] = _earnings_move_pct(df, d)
                stock["sessions_since_earnings"] = _sessions_since(
                    df.index if df is not None else None, d)
            n += 1
    return n


# --- Pre-trade context (Sakshar's ask, 2026-11-11): the four things the
# Friday analysis said to start tracking, captured per fade candidate so the
# 6:22 pre-trade check can drop names that should not be traded. All three
# getters are best-effort: they return None on failure (unknown), never a
# fake-empty result -- the caller logs loudly and the check fails open.
_FINANCING_PHRASES = (
    "convertible note", "convertible senior", "secondary offering",
    "follow-on offering", "follow on offering", "public offering",
    "private placement", "proposed offering", "announces offering",
    "announces pricing", "prices offering", "upsizes offering",
    "upsized offering", "offering of common stock", "notes offering",
    "senior notes",
)
_GUIDANCE_CUT_PHRASES = (
    "lowers guidance", "cuts guidance", "cuts outlook", "lowers outlook",
    "withdraws guidance", "suspends guidance",
)


def get_analyst_tape(ticker: str, index=None,
                     sessions: int = 5, as_of: date | None = None) -> dict | None:
    """Analyst actions for `ticker` in the last `sessions` sessions.

    Source: yfinance upgrades/downgrades history. `as_of` caps the window
    (default today) so a backtest never counts actions after its as-of date.
    Returns counts plus the latest actions, or None when the lookup fails
    (unknown). An empty history is a valid result (no actions on record),
    not a failure.
    """
    as_of = as_of or date.today()
    try:
        ud = yf.Ticker(ticker).upgrades_downgrades
    except Exception:  # noqa: BLE001
        return None
    if ud is None or ud.empty:
        return {"status": "ok", "upgrades": 0, "downgrades": 0,
                "raises": 0, "lowers": 0, "net": 0, "tape_net": 0, "latest": []}
    try:
        if index is not None and len(index) > 0:
            cutoff = index[-min(sessions, len(index))]
            recent = ud.loc[(ud.index >= cutoff)
                            & (ud.index < pd.Timestamp(as_of) + pd.Timedelta(days=1))]
        else:
            cutoff = pd.Timestamp.now(tz="US/Eastern") - pd.Timedelta(days=10)
            recent = ud.loc[ud.index >= cutoff]
    except Exception:  # noqa: BLE001
        return None
    if recent.empty:
        return {"status": "ok", "upgrades": 0, "downgrades": 0,
                "raises": 0, "lowers": 0, "net": 0, "tape_net": 0, "latest": []}
    up = int((recent["Action"] == "up").sum())
    down = int((recent["Action"] == "down").sum())
    raises = int((recent["priceTargetAction"] == "Raises").sum())
    lowers = int((recent["priceTargetAction"] == "Lowers").sum())
    # tape_net: positive = the Street is warming to the name (upgrades and
    # target raises); negative = cooling (downgrades and target lowers).
    # A short fade fights a positive tape; a long fade fights a negative one.
    tape_net = (up + raises) - (down + lowers)
    latest = []
    for ts, row in recent.head(3).iterrows():
        latest.append({
            "date": ts.date().isoformat(),
            "firm": str(row.get("Firm", "")),
            "action": str(row.get("Action", "")),
            "to_grade": str(row.get("ToGrade", "")),
            "target": (float(row["currentPriceTarget"])
                       if pd.notna(row.get("currentPriceTarget")) else None),
        })
    return {"status": "ok", "upgrades": up, "downgrades": down,
            "raises": raises, "lowers": lowers, "net": up - down,
            "tape_net": tape_net,
            "latest": latest}


def get_corporate_flags(ticker: str, index=None,
                        sessions: int = 5, as_of: date | None = None) -> list | None:
    """Financing / guidance-cut events for `ticker` in the last sessions.

    Source: Google News RSS (one targeted query per ticker). `as_of` caps
    the window (default today). Returns a list of {date, title, kind} with
    kind "financing" or "guidance_cut", or None when the lookup fails
    (unknown). An empty list means no matching event found in the window.

    Relevance: Google's RSS matching is loose (a query for APP once returned
    a Dropbox converts story), so a title only counts if it names the ticker
    as a word or the company's first name word (e.g. "Dropbox" for DBX).
    """
    as_of = as_of or date.today()
    try:
        # yfinance .info has no timeout of its own and can hang; bound it.
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        def _info():
            return yf.Ticker(ticker).info or {}

        with ThreadPoolExecutor(max_workers=1) as pool:
            info = pool.submit(_info).result(timeout=10)
        name = (info.get("shortName") or info.get("longName") or "")
        name_token = name.split()[0] if name else None
    except Exception:  # noqa: BLE001 - no name, fall back to ticker-only
        name_token = None
    try:
        q = urllib.parse.quote(
            f'"{ticker}" convertible notes offering OR "{ticker}" '
            f'secondary offering OR "{ticker}" follow-on offering OR '
            f'"{ticker}" public offering OR "{ticker}" private placement')
        req = urllib.request.Request(
            "https://news.google.com/rss/search?q=" + q +
            "&hl=en-US&gl=US&ceid=US:en",
            headers={"User-Agent": _FINVIZ_UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            root = ET.fromstring(resp.read())
    except Exception:  # noqa: BLE001
        return None
    if index is not None and len(index) > 0:
        cutoff = index[-min(sessions, len(index))].date()
    else:
        cutoff = date.today() - timedelta(days=10)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        pub = item.findtext("pubDate") or ""
        try:
            pub_date = parsedate_to_datetime(pub).date()
        except (ValueError, TypeError):
            continue
        if pub_date < cutoff or pub_date > as_of:
            continue
        low = title.lower()
        if not (re.search(rf"\b{re.escape(ticker.lower())}\b", low)
                or (name_token and name_token.lower() in low)):
            continue
        if any(p in low for p in _FINANCING_PHRASES):
            out.append({"date": pub_date.isoformat(), "title": title,
                        "kind": "financing"})
        elif any(p in low for p in _GUIDANCE_CUT_PHRASES):
            out.append({"date": pub_date.isoformat(), "title": title,
                        "kind": "guidance_cut"})
    return out


def annotate_context(result: dict, ohlcv: dict | None = None,
                     as_of: date | None = None) -> dict:
    """Attach analyst tape + corporate flags to each fade row.

    Mutates `result` in place. Returns a summary of how many rows got each
    annotation and how many lookups failed (unknown). A failed lookup leaves
    the field as None -- the dashboard shows "unknown", the 6:22 check treats
    it as no evidence (fails open), never as a clean bill of health.
    `as_of` caps the news/tape window (default: the result's date, else today).
    """
    if as_of is None:
        try:
            as_of = date.fromisoformat(result.get("date", ""))
        except ValueError:
            as_of = date.today()
    summary = {"analyst_ok": 0, "analyst_failed": 0,
               "corporate_ok": 0, "corporate_failed": 0}
    for stock in result.get("stocks", []):
        ticker = stock.get("ticker")
        df = (ohlcv or {}).get(ticker) if ohlcv else None
        index = df.index if df is not None else None
        tape = get_analyst_tape(ticker, index, as_of=as_of)
        if tape is None:
            stock["analyst_tape"] = None
            summary["analyst_failed"] += 1
        else:
            stock["analyst_tape"] = tape
            summary["analyst_ok"] += 1
        flags = get_corporate_flags(ticker, index, as_of=as_of)
        if flags is None:
            stock["corporate_flags"] = None
            summary["corporate_failed"] += 1
        else:
            if flags:
                for f in flags:
                    f["sessions_since"] = _sessions_since(index, f["date"])
            stock["corporate_flags"] = flags
            summary["corporate_ok"] += 1
    return summary


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


_OHLCV_FIELDS = ("Open", "High", "Low", "Close", "Volume")


def _download_chunk(tickers: list[str], period: str) -> dict[str, pd.DataFrame]:
    """Download one chunk; returns {field: wide DataFrame} for the OHLCV fields."""
    try:
        raw = yf.download(tickers, period=period, progress=False, auto_adjust=True)
    except Exception as e:
        print(f"Warning: chunk download failed ({e}), will retry")
        return {}
    out: dict[str, pd.DataFrame] = {}
    for field in _OHLCV_FIELDS:
        try:
            frame = raw[field]
        except KeyError:
            continue
        if isinstance(frame, pd.Series):
            frame = frame.to_frame(name=tickers[0])
        out[field] = frame
    return out


def _drop_trailing_empty_row(
    close: pd.DataFrame, high: pd.DataFrame, threshold: float = 0.5
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Drops trailing rows where most tickers are NaN (a pre-market placeholder day).

    Yahoo appends a placeholder row for "today" before the market opens, with
    no close price yet -- if left in, every `.iloc[-1]` call downstream (EMAs,
    52w high, momentum returns) would silently compute against NaN. Requiring
    *every* ticker to be NaN missed this in practice: a handful of tickers
    often already carry a value even before the broader market opens, so the
    row was rarely 100% NaN even though the vast majority of it was -- leaving
    most of the universe's momentum calculations silently NaN every morning
    run. A majority-NaN threshold catches the placeholder row without risking
    a real trading day being dropped over a few isolated per-ticker gaps.
    """
    while len(close) > 0 and close.iloc[-1].isna().mean() > threshold:
        close = close.iloc[:-1]
        high = high.iloc[:-1]
    return close, high


def download_prices(
    tickers: list[str],
    period: str = "1y",
    extra_tickers: list[str] | None = None,
    include_ohlcv: bool = False,
) -> tuple:
    """Downloads Close/High prices for `tickers` plus `extra_tickers` in chunks.

    Yahoo rate-limits large single-batch downloads (yfinance swallows the 429s
    per-ticker rather than raising, leaving those columns NaN). To work around
    this, tickers are fetched in small chunks with a delay between them, and
    any ticker that came back with no data is retried (with backoff) up to
    `_MAX_RETRIES` times before being given up on.

    Returns (universe, extras): `universe` is the Close-price frame for `tickers`,
    filtered to columns with sufficient history. `extras` maps each extra ticker
    (e.g. index symbols like SPY/^VIX that shouldn't go through the universe
    history filter or appear in the momentum screeners) to its own close/high frame.

    With include_ohlcv=True a third element is returned: `ohlcv`, mapping each
    universe ticker to its own Open/High/Low/Close/Volume DataFrame (same single
    batched download, no extra Yahoo requests).
    """
    extra_tickers = extra_tickers or []
    all_tickers = list(dict.fromkeys(tickers + extra_tickers))

    parts: dict[str, list[pd.DataFrame]] = {f: [] for f in _OHLCV_FIELDS}
    pending = all_tickers
    for attempt in range(_MAX_RETRIES + 1):
        if not pending:
            break
        if attempt > 0:
            print(f"Retrying {len(pending)} ticker(s) with no data (attempt {attempt + 1})")
            time.sleep(_RETRY_DELAY_SECONDS)

        still_missing = []
        for chunk in _chunked(pending, _CHUNK_SIZE):
            frames = _download_chunk(chunk, period)
            close_chunk = frames.get("Close")
            got = [
                t for t in chunk
                if close_chunk is not None
                and t in close_chunk.columns
                and close_chunk[t].notna().any()
            ]
            if got:
                for field, frame in frames.items():
                    cols = [t for t in got if t in frame.columns]
                    if cols:
                        parts[field].append(frame[cols])
            still_missing.extend(t for t in chunk if t not in got)
            time.sleep(_CHUNK_DELAY_SECONDS)
        pending = still_missing

    if pending:
        print(f"Warning: {len(pending)} ticker(s) had no data after {_MAX_RETRIES + 1} attempts")

    wide = {f: (pd.concat(p, axis=1) if p else pd.DataFrame()) for f, p in parts.items()}
    close, high = _drop_trailing_empty_row(wide["Close"], wide["High"])
    # keep the remaining fields aligned with the trimmed close frame
    aligned = {
        f: (wide[f].loc[close.index] if not wide[f].empty else wide[f])
        for f in _OHLCV_FIELDS
    }

    extras = {
        t: pd.DataFrame({"close": close[t], "high": high[t]})
        for t in extra_tickers
        if t in close.columns
    }

    universe = close.drop(columns=extra_tickers, errors="ignore")
    universe = universe.dropna(axis=1, thresh=int(len(universe) * 0.9))
    if universe.empty:
        raise ValueError("No price data returned after filtering")

    if not include_ohlcv:
        return universe, extras

    ohlcv = {
        t: pd.DataFrame({f: aligned[f][t] for f in _OHLCV_FIELDS}).dropna(subset=["Close"])
        for t in universe.columns
        if all(t in aligned[f].columns for f in _OHLCV_FIELDS)
    }
    return universe, extras, ohlcv


def compute_momentum(data: pd.DataFrame) -> pd.DataFrame:
    if len(data) < 189:
        raise ValueError(f"Price history too short: {len(data)} rows, need at least 189")
    returns = pd.DataFrame(index=data.columns)
    returns["1M"] = (data.iloc[-1] / data.iloc[-21]).values - 1
    returns["3M"] = (data.iloc[-1] / data.iloc[-63]).values - 1
    returns["6M"] = (data.iloc[-1] / data.iloc[-126]).values - 1
    returns["9M"] = (data.iloc[-1] / data.iloc[-189]).values - 1
    ranks = returns.rank(pct=True)
    returns["avg_rank"] = ranks.mean(axis=1)
    return returns
