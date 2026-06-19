import json
from datetime import date
from pathlib import Path

import yfinance as yf


def classify_ema_signal(ema10: float, ema20: float) -> str:
    return "bullish" if ema10 > ema20 else "bearish"


def classify_vix_level(vix: float) -> str:
    if vix < 15:
        return "low"
    elif vix < 20:
        return "normal"
    elif vix <= 30:
        return "elevated"
    else:
        return "crisis"


def write_json(data: dict, path: str = "data/latest.json") -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
