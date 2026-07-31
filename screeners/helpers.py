import time
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf
from finvizfinance.screener.overview import Overview

_FALLBACK_TICKERS = ["NVDA", "TSLA", "PLTR", "SMCI", "ARM", "AAPL"]
_CHUNK_SIZE = 40
_CHUNK_DELAY_SECONDS = 2
_MAX_RETRIES = 2
_RETRY_DELAY_SECONDS = 8


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fix_finviz_ticker(ticker: str) -> str:
    """finvizfinance's HTML scraper grabs the full text of the ticker cell, which
    Finviz now renders as a one-letter avatar placeholder span (e.g. "Z") followed
    by the real ticker link ("ZYME") -- so `.text` comes back as "ZZYME". The
    duplicated character is always the ticker's own first letter, so stripping it
    reconstructs the real symbol regardless of length or hyphens.
    """
    return ticker[1:]


def get_finviz_tickers(filters: dict) -> list[str]:
    try:
        screen = Overview()
        screen.set_filter(filters_dict=filters)
        df = screen.screener_view()
        if df is not None and not df.empty:
            return [fix_finviz_ticker(t) for t in df["Ticker"].tolist()]
    except Exception as e:
        print(f"Warning: Finviz screener failed ({e}), using fallback tickers")
    return _FALLBACK_TICKERS.copy()


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _download_chunk(tickers: list[str], period: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        raw = yf.download(tickers, period=period, progress=False, auto_adjust=True)
    except Exception as e:
        print(f"Warning: chunk download failed ({e}), will retry")
        return pd.DataFrame(), pd.DataFrame()
    close, high = raw["Close"], raw["High"]
    if isinstance(close, pd.Series):
        close = close.to_frame(name=tickers[0])
        high = high.to_frame(name=tickers[0])
    return close, high


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
    tickers: list[str], period: str = "1y", extra_tickers: list[str] | None = None
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
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
    """
    extra_tickers = extra_tickers or []
    all_tickers = list(dict.fromkeys(tickers + extra_tickers))

    close_parts, high_parts = [], []
    pending = all_tickers
    for attempt in range(_MAX_RETRIES + 1):
        if not pending:
            break
        if attempt > 0:
            print(f"Retrying {len(pending)} ticker(s) with no data (attempt {attempt + 1})")
            time.sleep(_RETRY_DELAY_SECONDS)

        still_missing = []
        for chunk in _chunked(pending, _CHUNK_SIZE):
            close, high = _download_chunk(chunk, period)
            got = [t for t in chunk if t in close.columns and close[t].notna().any()]
            if got:
                close_parts.append(close[got])
                high_parts.append(high[got])
            still_missing.extend(t for t in chunk if t not in got)
            time.sleep(_CHUNK_DELAY_SECONDS)
        pending = still_missing

    if pending:
        print(f"Warning: {len(pending)} ticker(s) had no data after {_MAX_RETRIES + 1} attempts")

    close = pd.concat(close_parts, axis=1) if close_parts else pd.DataFrame()
    high = pd.concat(high_parts, axis=1) if high_parts else pd.DataFrame()
    close, high = _drop_trailing_empty_row(close, high)

    extras = {
        t: pd.DataFrame({"close": close[t], "high": high[t]})
        for t in extra_tickers
        if t in close.columns
    }

    universe = close.drop(columns=extra_tickers, errors="ignore")
    universe = universe.dropna(axis=1, thresh=int(len(universe) * 0.9))
    if universe.empty:
        raise ValueError("No price data returned after filtering")

    return universe, extras


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
