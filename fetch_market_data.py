import json
from datetime import date
from pathlib import Path

import yfinance as yf

from screeners import helpers, parabolic_short, qullamaggie, relative_strength


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


def get_spy_ema_signal() -> dict:
    spy = yf.download("SPY", period="60d", interval="1d", progress=False)
    if spy.empty:
        raise ValueError("No SPY data returned from yfinance")
    close = spy["Close"].squeeze()
    ema10 = float(close.ewm(span=10, adjust=False).mean().iloc[-1])
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])

    fi = yf.Ticker("SPY").fast_info
    last_close = round(float(fi.previous_close), 2)
    high_52w = round(float(fi.year_high), 2)
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
    # --- Market indicators (existing) ---
    try:
        payload = {"date": date.today().isoformat()}
        payload.update(get_spy_ema_signal())
        payload.update(get_vix_data())
        write_json(payload)
        print(f"Written: {payload}")
    except ValueError as e:
        print(f"Skipping market indicators update: {e}")

    # --- Parabolic short (independent — Finviz Performance only, no yfinance) ---
    try:
        result = parabolic_short.run()
        write_json(result, "data/parabolic_short.json")
        print(f"Parabolic short: {sum(len(b['tickers']) for b in result['bands'])} tickers across {len(result['bands'])} bands")
    except Exception as e:
        print(f"Skipping parabolic short: {e}")

    # --- Shared large-cap universe fetch (used by both Qullamaggie and RS) ---
    _LARGE_CAP_FILTERS = {
        "Market Cap.": "+Large (over $10bln)",
        "Price": "Over $20",
        "Average Volume": "Over 500K",
        "Country": "USA",
    }
    try:
        tickers    = helpers.get_finviz_tickers(_LARGE_CAP_FILTERS)
        price_data = helpers.download_prices(tickers)
        momentum   = helpers.compute_momentum(price_data)
        print(f"Universe: {len(tickers)} tickers fetched, {price_data.shape[1]} with sufficient history")
    except Exception as e:
        print(f"Skipping Qullamaggie + RS: failed to fetch universe: {e}")
        return

    # --- Qullamaggie ---
    try:
        result = qullamaggie.run(price_data, momentum)
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
