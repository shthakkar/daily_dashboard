import json
from datetime import date
from pathlib import Path

import pandas as pd

from screeners import capitulation_fade, helpers, news_movers, qullamaggie, relative_strength


def classify_ema_signal(ema10: float, ema20: float) -> str:
    return "bullish" if ema10 > ema20 else "bearish"


def classify_spy_off_high(pct: float) -> str:
    if pct >= -5:
        return "near-high"
    elif pct >= -10:
        return "mild-off"
    elif pct >= -20:
        return "off-high"
    else:
        return "far-off"


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


def get_spy_ema_signal(spy: pd.DataFrame) -> dict:
    close = spy["close"]
    if pd.isna(close.iloc[-1]):
        raise ValueError("SPY close is NaN (likely a pre-market placeholder row)")
    ema10 = float(close.ewm(span=10, adjust=False).mean().iloc[-1])
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])

    last_close = round(float(close.iloc[-1]), 2)
    high_52w = round(float(spy["high"].max()), 2)
    pct_off_high = round((last_close - high_52w) / high_52w * 100, 2)
    return {
        "spy_ema": classify_ema_signal(ema10, ema20),
        "spy_10ema": round(ema10, 2),
        "spy_20ema": round(ema20, 2),
        "spy_last_close": last_close,
        "spy_52w_high": high_52w,
        "spy_pct_off_high": pct_off_high,
        "spy_off_high_level": classify_spy_off_high(pct_off_high),
    }


def get_vix_data(vix: pd.DataFrame) -> dict:
    vix_value = float(vix["close"].iloc[-1])
    if pd.isna(vix_value):
        raise ValueError("VIX close is NaN (likely a pre-market placeholder row)")
    return {
        "vix": round(vix_value, 2),
        "vix_level": classify_vix_level(vix_value),
    }


def main() -> None:
    # --- Single batched yfinance call: large+mid-cap universe + SPY + VIX ---
    # Combined into one request so the run stays under Yahoo's rate limit
    # instead of issuing separate SPY/VIX/universe calls. The capitulation
    # fade screener covers mid caps too (framework targets $2B+), while the
    # momentum screeners below keep the original large-cap-only universe so
    # their outputs don't change.
    _LARGE_CAP_FILTERS = {
        "Market Cap.": "+Large (over $10bln)",
        "Price": "Over $20",
        "Average Volume": "Over 500K",
        "Country": "USA",
    }
    _MID_CAP_FILTERS = {
        "Market Cap.": "Mid ($2bln to $10bln)",
        "Price": "Over $20",
        "Average Volume": "Over 500K",
        "Country": "USA",
    }
    try:
        large_tickers = helpers.get_finviz_tickers(_LARGE_CAP_FILTERS)
        mid_tickers = helpers.get_finviz_tickers(_MID_CAP_FILTERS)
        tickers = list(dict.fromkeys(large_tickers + mid_tickers))
        price_data, extras, ohlcv = helpers.download_prices(
            tickers, extra_tickers=["SPY", "^VIX"], include_ohlcv=True
        )
        large_cols = [t for t in large_tickers if t in price_data.columns]
        price_large = price_data[large_cols]
        momentum = helpers.compute_momentum(price_large)
        print(
            f"Universe: {len(tickers)} tickers fetched, "
            f"{price_data.shape[1]} with sufficient history "
            f"({len(ohlcv)} with OHLCV)"
        )
    except Exception as e:
        print(f"Skipping everything: failed to fetch price data: {e}")
        return

    # --- Market indicators ---
    try:
        payload = {"date": date.today().isoformat(), "updated_at": helpers.now_utc_iso()}
        payload.update(get_spy_ema_signal(extras["SPY"]))
        payload.update(get_vix_data(extras["^VIX"]))
        write_json(payload)
        print(f"Written: {payload}")
    except Exception as e:
        print(f"Skipping market indicators update: {e}")

    # --- Capitulation Fade (needs OHLCV; screens the large+mid universe) ---
    try:
        result = capitulation_fade.run(ohlcv)
        write_json(result, "data/capitulation_fade.json")
        print(f"Capitulation fade: {len(result['stocks'])} candidates")
    except Exception as e:
        print(f"Skipping capitulation fade: {e}")

    # --- News Movers (independent — Finviz Custom screener only, no yfinance) ---
    try:
        result = news_movers.run()
        write_json(result, "data/news_movers.json")
        print(f"News movers: {len(result['stocks'])} stocks")
    except Exception as e:
        print(f"Skipping news movers: {e}")

    # --- Qullamaggie ---
    try:
        result = qullamaggie.run(price_large, momentum)
        write_json(result, "data/qullamaggie.json")
        print(f"Qullamaggie: {len(result['stocks'])} stocks")
    except Exception as e:
        print(f"Skipping Qullamaggie: {e}")

    # --- Relative Strength ---
    try:
        result = relative_strength.run(momentum)
        write_json(result, "data/relative_strength.json")
        print(f"Relative strength: {len(result['stocks'])} stocks")
    except Exception as e:
        print(f"Skipping relative strength: {e}")


if __name__ == "__main__":
    main()
