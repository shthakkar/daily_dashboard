from datetime import date

import pandas as pd


def _compute_tightness_score(
    close: float, ema10: float, ema20: float, sma50: float
) -> float:
    d10_20    = abs(ema10 - ema20) / close * 100
    d20_50    = abs(ema20 - sma50) / close * 100
    dprice_10 = abs(close - ema10) / close * 100
    score = (
        max(0.0, 4.5 - d10_20 * 1.8)
        + max(0.0, 3.5 - d20_50 * 0.45)
        + max(0.0, 2.0 - dprice_10 * 0.35)
    )
    return round(max(1.0, min(10.0, score)), 1)


def _rate_tightness(score: float) -> str:
    if score >= 8.5:
        return "Extremely Tight"
    if score >= 7.0:
        return "Very Tight"
    if score >= 5.5:
        return "Tight"
    if score >= 4.0:
        return "Medium"
    return "Wide"


def run(data: pd.DataFrame, momentum: pd.DataFrame) -> dict:
    top = momentum[momentum["avg_rank"] >= 0.92]
    results = []
    for ticker in top.index:
        if ticker not in data.columns:
            continue
        try:
            series = data[ticker].dropna()
            close  = float(series.iloc[-1])
            ema10  = float(series.ewm(span=10, adjust=False).mean().iloc[-1])
            ema20  = float(series.ewm(span=20, adjust=False).mean().iloc[-1])
            sma50  = float(series.rolling(50).mean().iloc[-1])
            tightness = _compute_tightness_score(close, ema10, ema20, sma50)
            results.append({
                "ticker":    ticker,
                "tightness": tightness,
                "rating":    _rate_tightness(tightness),
                "close":     round(close, 2),
                "avg_rank":  round(float(top.loc[ticker, "avg_rank"]), 4),
            })
        except Exception:
            pass
    results.sort(key=lambda x: x["tightness"], reverse=True)
    return {"date": date.today().isoformat(), "stocks": results}
