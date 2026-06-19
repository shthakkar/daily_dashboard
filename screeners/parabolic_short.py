from datetime import date

import pandas as pd
from finvizfinance.screener.performance import Performance

_BANDS = [
    {"label": "Small Cap", "cap": "Small ($300mln to $2bln)"},
    {"label": "Mid Cap",   "cap": "Mid ($2bln to $10bln)"},
    {"label": "Large Cap", "cap": "Large ($10bln to $200bln)"},
]


def _rows_from_df(df) -> list[dict]:
    if df is None or df.empty:
        return []
    return [
        {
            "ticker": str(row["Ticker"]),
            "perf_week": str(row["Perf Week"]),
            "perf_month": str(row["Perf Month"]),
        }
        for _, row in df.head(5).iterrows()
    ]


def _fetch_band(cap_filter: str) -> list[dict]:
    screen = Performance()
    screen.set_filter(filters_dict={"Country": "USA", "Market Cap.": cap_filter})
    df = screen.screener_view(order="Performance (Week)", ascend=False, verbose=0)
    return _rows_from_df(df)


def run() -> dict:
    bands = []
    for band in _BANDS:
        try:
            tickers = _fetch_band(band["cap"])
        except Exception as e:
            print(f"Warning: parabolic short band '{band['label']}' failed: {e}")
            tickers = []
        bands.append({"label": band["label"], "tickers": tickers})
    return {"date": date.today().isoformat(), "bands": bands}
