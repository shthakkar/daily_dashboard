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
        f.write("\n")


def get_spy_ema_signal() -> dict:
    spy = yf.download("SPY", period="60d", interval="1d", progress=False)
    if spy.empty:
        raise ValueError("No SPY data returned from yfinance")
    close = spy["Close"].squeeze()
    ema10 = float(close.ewm(span=10, adjust=False).mean().iloc[-1])
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    return {
        "spy_ema": classify_ema_signal(ema10, ema20),
        "spy_10ema": round(ema10, 2),
        "spy_20ema": round(ema20, 2),
    }


def get_vix_data() -> dict:
    vix_df = yf.download("^VIX", period="10d", interval="1d", progress=False)
    if vix_df.empty:
        raise ValueError("No VIX data returned from yfinance")
    vix_value = float(vix_df["Close"].squeeze().iloc[-1])
    return {
        "vix": round(vix_value, 2),
        "vix_level": classify_vix_level(vix_value),
    }


def main() -> None:
    try:
        payload = {"date": date.today().isoformat()}
        payload.update(get_spy_ema_signal())
        payload.update(get_vix_data())
        write_json(payload)
        print(f"Written: {payload}")
    except ValueError as e:
        # Market closed or holiday — leave latest.json unchanged
        print(f"Skipping update: {e}")


if __name__ == "__main__":
    main()
