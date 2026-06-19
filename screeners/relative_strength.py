from datetime import date

import pandas as pd


def _fmt(v: float) -> str:
    return f"{v:+.1%}"


def run(momentum: pd.DataFrame) -> dict:
    top = momentum[momentum["avg_rank"] >= 0.97].sort_values("avg_rank", ascending=False)
    stocks = [
        {
            "ticker":   ticker,
            "avg_rank": round(float(row["avg_rank"]), 4),
            "ret_1m":   _fmt(row["1M"]),
            "ret_3m":   _fmt(row["3M"]),
            "ret_6m":   _fmt(row["6M"]),
            "ret_9m":   _fmt(row["9M"]),
        }
        for ticker, row in top.iterrows()
    ]
    return {"date": date.today().isoformat(), "stocks": stocks}
