# Daily Market Dashboard — Design Spec

**Date:** 2026-06-19  
**Status:** Approved

## Overview

A lightweight daily market dashboard that shows two market regime indicators — SPY trend direction and VIX volatility level — updated each morning before market open. A Python script fetches and computes the data, writes it to a static JSON file, which is committed to the repo and served via GitHub Pages. The dashboard is a single HTML file that reads the JSON on page load.

## Goals

- Show at a glance whether the market is bullish/bearish and how volatile it is
- Zero infrastructure cost (no database, no server, no paid APIs)
- Local-first: works by running the script manually and opening `index.html`
- Automated: GitHub Actions commits fresh data each weekday morning

## Non-Goals (POC scope)

- No historical data storage or trend charts
- No individual stock screener (planned for a future phase)
- No user authentication or personalization
- No TradingView widgets (future phase, when tickers are added)

---

## Data Flow

```
fetch_market_data.py
    ↓  yfinance pulls SPY daily candles + ^VIX daily close
    ↓  computes 10EMA, 20EMA, VIX level
    ↓  writes
data/latest.json
    ↓  committed to repo by GitHub Actions (weekdays, 6am ET)
    ↓  served as static asset via GitHub Pages
index.html
    ↓  fetch('data/latest.json') on page load
    ↓  renders two indicator cards
```

---

## Python Script: `fetch_market_data.py`

**Dependencies:** `yfinance` only (no other third-party packages).

**Logic:**

1. Pull SPY daily OHLCV for the last 30 days via `yfinance`.
2. Compute 10-period EMA and 20-period EMA on the closing price.
3. If `10EMA > 20EMA` → `spy_ema = "bullish"`, else → `spy_ema = "bearish"`.
4. Pull `^VIX` daily close for today via `yfinance`.
5. Map VIX value to level:
   - `< 15` → `"low"`
   - `15–20` → `"normal"`
   - `20–30` → `"elevated"`
   - `> 30` → `"crisis"`
6. Write `data/latest.json`.

**Output schema:**

```json
{
  "date": "2026-06-19",
  "spy_ema": "bullish",
  "spy_10ema": 534.21,
  "spy_20ema": 529.87,
  "vix": 18.4,
  "vix_level": "normal"
}
```

**Edge cases:**
- If yfinance returns no data (holiday, market closed), the script exits without overwriting `latest.json` — the previous day's data stays on the dashboard.
- Script is idempotent: safe to run multiple times per day; output is always the latest computed values.

---

## Dashboard: `index.html`

A single self-contained HTML file. No build step, no framework, no CDN dependencies except the inline fetch.

**Layout:** Two cards side by side (flex row, wraps on mobile).

**Card 1 — Market Direction:**
- Large label: `BULLISH` (green) or `BEARISH` (red)
- Subtitle: `SPY 10EMA: 534.21 | 20EMA: 529.87`
- Date of last update shown below

**Card 2 — Volatility:**
- Large label: `LOW` / `NORMAL` / `ELEVATED` / `CRISIS`
- Color coding: green / yellow / orange / red
- Subtitle: `VIX: 18.4`

**Error state:** If the fetch fails or JSON is malformed, show a gray "Data unavailable" state rather than breaking the page.

**Styling:** Minimal inline CSS — dark background, large readable text, no external stylesheet dependencies.

---

## GitHub Actions Workflow: `.github/workflows/daily_update.yml`

**Trigger:** Cron `0 11 * * 1-5` (11:00 UTC = 6:00am ET, weekdays only).

**Steps:**
1. Checkout repo
2. Set up Python 3.11
3. `pip install yfinance`
4. Run `python fetch_market_data.py`
5. If `data/latest.json` changed: commit with message `data: update market indicators [skip ci]` and push to `main`

**Note:** `[skip ci]` in the commit message prevents the push from re-triggering the workflow in CI systems that watch for pushes.

---

## Repository Structure

```
daily_dashboard/
├── index.html                          # Dashboard UI
├── fetch_market_data.py                # Data fetch + compute script
├── data/
│   └── latest.json                     # Output written by script, read by dashboard
├── .github/
│   └── workflows/
│       └── daily_update.yml            # GitHub Actions cron workflow
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-06-19-daily-dashboard-design.md
```

---

## Local Development

1. `pip install yfinance`
2. `python fetch_market_data.py` — writes `data/latest.json`
3. Open `index.html` in browser — reads the JSON via `fetch()`

> Note: browsers block `fetch()` on `file://` URLs due to CORS. Run a local server instead:  
> `python -m http.server 8000` then open `http://localhost:8000`

---

## GitHub Pages Setup

1. Push repo to GitHub
2. In repo Settings → Pages → Source: `main` branch, root `/`
3. Dashboard available at `https://<username>.github.io/daily_dashboard/`

---

## Future Phases

- **Stock screener:** Python script screens a universe of stocks by EMA crossover or momentum, stores top picks as an array in `latest.json`, dashboard renders a ticker list with TradingView chart widgets on click/hover.
- **Historical tracking:** Add `data/history.json` appended daily for trend visualization.
- **Supabase:** Add if historical querying or multi-user features are needed.
