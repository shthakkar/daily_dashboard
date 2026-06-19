# Scanner Sections — Design Spec

**Date:** 2026-06-19  
**Status:** Approved

## Overview

Add three scanner sections to the daily dashboard: Parabolic Short Setups, Qullamaggie MA Tightness, and Relative Strength. Each scanner runs as part of the existing daily GitHub Actions workflow, writes its own JSON file, and is rendered as a new section in `index.html` with ticker pills (TradingView hover popup) and metric columns.

## Goals

- Surface actionable stock setups daily alongside the existing market regime indicators
- Reuse the expensive Finviz + yfinance fetch across Qullamaggie and RS scanners (run once, shared)
- Keep each scanner independently testable by isolating it in its own module
- Zero additional infrastructure cost — same static JSON → GitHub Pages pattern

## Non-Goals

- No historical scanner output storage
- No user-configurable thresholds or filters
- No intraday refresh (daily cadence only)

---

## Python Module Structure

```
daily_dashboard/
├── fetch_market_data.py          ← orchestrator (existing, extended)
├── screeners/
│   ├── __init__.py
│   ├── helpers.py                ← shared utilities
│   ├── parabolic_short.py
│   ├── qullamaggie.py
│   └── relative_strength.py
├── data/
│   ├── latest.json               ← existing (SPY EMA + VIX)
│   ├── parabolic_short.json      ← new
│   ├── qullamaggie.json          ← new
│   └── relative_strength.json   ← new
```

---

## `screeners/helpers.py`

Three shared functions:

### `get_finviz_tickers(filters: dict) -> list[str]`
- Uses `finvizfinance.screener.overview.Overview`
- Sets filters and calls `screener_view()`
- Returns `df['Ticker'].tolist()` or a small fallback list if the screener returns nothing

### `download_prices(tickers: list[str], period: str = "1y") -> pd.DataFrame`
- Calls `yf.download(tickers, period=period, progress=False, auto_adjust=True)["Close"]`
- Drops columns with more than 10% missing values (`dropna(thresh=len(data)*0.9)`)
- Returns the cleaned DataFrame

### `compute_momentum(data: pd.DataFrame) -> pd.DataFrame`
- Computes returns: 1M (`iloc[-21]`), 3M (`iloc[-63]`), 6M (`iloc[-126]`), 9M (`iloc[-189]`)
- Ranks each column percentile-wise, averages ranks into `avg_rank`
- Returns DataFrame indexed by ticker with columns: `1M`, `3M`, `6M`, `9M`, `avg_rank`

---

## `screeners/parabolic_short.py`

### `run() -> dict`

Uses `finvizfinance.screener.performance.Performance` (not Overview — no yfinance needed).

**Logic:**
1. For each of 3 cap bands (Small `$300M–$2B`, Mid `$2B–$10B`, Large `$10B–$200B`):
   - Set filters: `Country=USA`, `Market Cap.=<band>`
   - Order by `Performance (Week)` descending
   - Take top 5 rows: `["Ticker", "Perf Week", "Perf Month"]`
2. Return structured dict (see schema below)

**Output schema (`data/parabolic_short.json`):**
```json
{
  "date": "2026-06-19",
  "bands": [
    {
      "label": "Small Cap",
      "tickers": [
        {"ticker": "XYZ", "perf_week": "+18.4%", "perf_month": "+32.1%"}
      ]
    },
    {"label": "Mid Cap", "tickers": [...]},
    {"label": "Large Cap", "tickers": [...]}
  ]
}
```

---

## `screeners/qullamaggie.py`

### `run(data: pd.DataFrame, momentum: pd.DataFrame) -> dict`

Receives pre-fetched price data and pre-computed momentum from the orchestrator.

**Logic:**
1. Filter `momentum` to top 8% by `avg_rank` (`avg_rank >= 0.92`)
2. For each ticker in the filtered set, compute tightness score:
   - `ema10`, `ema20` via `ewm(span=10/20)`; `sma50` via `rolling(50)` — from `data[ticker]`
   - `d10_20 = |ema10 - ema20| / close * 100`
   - `d20_50 = |ema20 - sma50| / close * 100`
   - `dprice_10 = |close - ema10| / close * 100`
   - Score: `score_10_20 = max(0, 4.5 - d10_20*1.8)` + `score_20_50 = max(0, 3.5 - d20_50*0.45)` + `score_price = max(0, 2.0 - dprice_10*0.35)`
   - `tightness_score = clamp(sum, 1, 10)`
3. Rating labels: `≥8.5` → Extremely Tight, `≥7.0` → Very Tight, `≥5.5` → Tight, `≥4.0` → Medium, else Wide
4. Sort by tightness descending

**Output schema (`data/qullamaggie.json`):**
```json
{
  "date": "2026-06-19",
  "stocks": [
    {
      "ticker": "NVDA",
      "tightness": 8.2,
      "rating": "Very Tight",
      "close": 142.50,
      "avg_rank": 0.9731
    }
  ]
}
```

---

## `screeners/relative_strength.py`

### `run(momentum: pd.DataFrame) -> dict`

Receives pre-computed momentum from the orchestrator (no price data needed beyond what helpers computed).

**Logic:**
1. Filter `momentum` to top 3% by `avg_rank` (`avg_rank >= 0.97`)
2. Sort by `avg_rank` descending
3. Format return columns as percentage strings

**Output schema (`data/relative_strength.json`):**
```json
{
  "date": "2026-06-19",
  "stocks": [
    {
      "ticker": "NVDA",
      "avg_rank": 0.9812,
      "ret_1m": "+12.3%",
      "ret_3m": "+28.1%",
      "ret_6m": "+54.2%",
      "ret_9m": "+71.8%"
    }
  ]
}
```

---

## `fetch_market_data.py` — Orchestration Changes

Extended `main()` sequence:

```
1. get_spy_ema_signal() + get_vix_data() → write data/latest.json   [unchanged]
2. get_finviz_tickers(large_cap_filters) → tickers
3. download_prices(tickers) → price_data
4. compute_momentum(price_data) → momentum
5. qullamaggie.run(price_data, momentum) → write data/qullamaggie.json
6. relative_strength.run(momentum) → write data/relative_strength.json
7. parabolic_short.run() → write data/parabolic_short.json
```

Each scanner is wrapped in its own `try/except` so a failure in one does not block the others.

---

## `requirements.txt` Changes

Add:
```
finvizfinance
```

(`pandas` is a transitive dependency of both `yfinance` and `finvizfinance` — no need to pin explicitly.)

---

## Dashboard: `index.html` Changes

### Three new sections below the existing watchlists

Each section is a `<div class="scanner-section">` with:
- A section title (same `watchlist-title` style)
- Rows where each ticker is a `.ticker` pill (`.long` green for Qullamaggie/RS, `.short` red for Parabolic Short) with `data-symbol` set for TradingView hover — reuses the **existing** `showPopup`/`hidePopup` JS with no changes needed
- Metric columns rendered as plain text spans beside each ticker row

### Parabolic Short
Three sub-columns (Small / Mid / Large Cap), each listing 5 tickers with `+X% 2W` and `+X% 4W`.

### Qullamaggie
Single list, columns: `[TICKER pill]  score  rating  $close`

### Relative Strength
Single list, columns: `[TICKER pill]  1M +X%  3M +X%  6M +X%  9M +X%`

### JS fetch additions
Three additional `fetch('data/<scanner>.json')` calls on page load, each populating their section. If any fetch fails, that section shows a gray "Data unavailable" state.

### Ticker symbol resolution
Finviz returns bare tickers (e.g. `NVDA`). The dashboard will attempt `NASDAQ:TICKER` as the TradingView symbol. For the MVP, this is acceptable — a future improvement could store the exchange alongside the ticker.

---

## GitHub Actions Changes

No workflow changes needed — the workflow already runs `python fetch_market_data.py` and commits all changed files under `data/`. The three new JSON files will be auto-committed alongside `latest.json`.

---

## Repository Structure (final)

```
daily_dashboard/
├── fetch_market_data.py
├── screeners/
│   ├── __init__.py
│   ├── helpers.py
│   ├── parabolic_short.py
│   ├── qullamaggie.py
│   └── relative_strength.py
├── data/
│   ├── latest.json
│   ├── parabolic_short.json
│   ├── qullamaggie.json
│   └── relative_strength.json
├── index.html
├── requirements.txt
├── .github/workflows/daily_update.yml
└── docs/superpowers/specs/
    ├── 2026-06-19-daily-dashboard-design.md
    └── 2026-06-19-scanners-design.md
```

---

## Edge Cases

- **Finviz rate-limiting:** If Finviz returns an error, `get_finviz_tickers()` returns the fallback list and logs a warning. Scanner still runs on fallback tickers.
- **Insufficient history:** Tickers with fewer than 189 trading days are excluded by `dropna(thresh=90%)` before momentum computation.
- **Market closed:** If yfinance returns no data, `download_prices()` raises `ValueError`; the orchestrator catches it per-scanner and leaves the existing JSON unchanged.
- **Empty screener result:** Each scanner returns `{"date": "...", "stocks": []}` (or `"bands": []`) rather than omitting the file, so the dashboard always has valid JSON to parse.
