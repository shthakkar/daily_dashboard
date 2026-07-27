import pandas as pd
import yfinance as yf
from finvizfinance.screener.overview import Overview

_FALLBACK_TICKERS = ["NVDA", "TSLA", "PLTR", "SMCI", "ARM", "AAPL"]


def get_finviz_tickers(filters: dict) -> list[str]:
    try:
        screen = Overview()
        screen.set_filter(filters_dict=filters)
        df = screen.screener_view()
        if df is not None and not df.empty:
            return df["Ticker"].tolist()
    except Exception as e:
        print(f"Warning: Finviz screener failed ({e}), using fallback tickers")
    return _FALLBACK_TICKERS.copy()


def download_prices(
    tickers: list[str], period: str = "1y", extra_tickers: list[str] | None = None
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Downloads Close/High prices for `tickers` plus `extra_tickers` in one batch call.

    Returns (universe, extras): `universe` is the Close-price frame for `tickers`,
    filtered to columns with sufficient history. `extras` maps each extra ticker
    (e.g. index symbols like SPY/^VIX that shouldn't go through the universe
    history filter or appear in the momentum screeners) to its own close/high frame.
    """
    extra_tickers = extra_tickers or []
    all_tickers = list(dict.fromkeys(tickers + extra_tickers))
    raw = yf.download(all_tickers, period=period, progress=False, auto_adjust=True)
    close, high = raw["Close"], raw["High"]
    if isinstance(close, pd.Series):
        close = close.to_frame(name=all_tickers[0])
        high = high.to_frame(name=all_tickers[0])

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
