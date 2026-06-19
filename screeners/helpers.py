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


def download_prices(tickers: list[str], period: str = "1y") -> pd.DataFrame:
    data = yf.download(tickers, period=period, progress=False, auto_adjust=True)["Close"]
    if isinstance(data, pd.Series):
        data = data.to_frame(name=tickers[0])
    data = data.dropna(axis=1, thresh=int(len(data) * 0.9))
    if data.empty:
        raise ValueError("No price data returned after filtering")
    return data


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
