# Daily Market Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally-runnable daily market dashboard that fetches SPY EMA trend and VIX volatility level, writes them to `data/latest.json`, and displays them in a static HTML page — with a GitHub Actions cron job to keep it updated automatically.

**Architecture:** Python script (`fetch_market_data.py`) uses `yfinance` to pull SPY daily candles and VIX, computes classifications, and writes `data/latest.json`. A single `index.html` file fetches that JSON on load and renders two indicator cards. GitHub Actions runs the script on a weekday cron and commits the updated JSON.

**Tech Stack:** Python 3.11+, yfinance, pytest, vanilla HTML/CSS/JS, GitHub Actions, GitHub Pages

---

## File Map

| File | Purpose |
|------|---------|
| `fetch_market_data.py` | Fetch + classify + write JSON |
| `data/latest.json` | Generated output read by the dashboard |
| `data/.gitkeep` | Keeps the `data/` dir in git before first run |
| `index.html` | Dashboard UI — two indicator cards |
| `requirements.txt` | Runtime dependency (yfinance) |
| `requirements-dev.txt` | Dev dependency (pytest) |
| `.gitignore` | Ignore `.pyc`, `__pycache__`, venv |
| `tests/test_fetch_market_data.py` | Unit tests for classification + JSON writing |
| `.github/workflows/daily_update.yml` | GitHub Actions cron workflow |

---

## Task 1: Project Bootstrap

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `.gitignore`
- Create: `data/.gitkeep`

- [ ] **Step 1: Create `requirements.txt`**

```
yfinance
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```
pytest
```

- [ ] **Step 3: Create `.gitignore`**

```
__pycache__/
*.pyc
*.pyo
.venv/
venv/
.env
```

- [ ] **Step 4: Create `data/.gitkeep`**

```bash
touch data/.gitkeep
```

- [ ] **Step 5: Install dependencies**

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

Expected: yfinance and pytest installed with no errors.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt requirements-dev.txt .gitignore data/.gitkeep
git commit -m "chore: project bootstrap"
```

---

## Task 2: Classification Functions (TDD)

Write the two pure classification functions first — these are the business logic with no I/O, so they're easy to test in isolation. The yfinance calls come in Task 3.

**Files:**
- Create: `fetch_market_data.py`
- Create: `tests/__init__.py`
- Create: `tests/test_fetch_market_data.py`

- [ ] **Step 1: Create `tests/__init__.py`**

```bash
mkdir tests && touch tests/__init__.py
```

- [ ] **Step 2: Write all classification tests in `tests/test_fetch_market_data.py`**

```python
import json
import os
import tempfile

import pytest

from fetch_market_data import classify_ema_signal, classify_vix_level, write_json


# --- classify_ema_signal ---

def test_classify_ema_signal_bullish():
    assert classify_ema_signal(535.0, 530.0) == "bullish"


def test_classify_ema_signal_bearish():
    assert classify_ema_signal(520.0, 530.0) == "bearish"


def test_classify_ema_signal_equal_is_bearish():
    # 10EMA == 20EMA is not strictly greater, so bearish
    assert classify_ema_signal(530.0, 530.0) == "bearish"


# --- classify_vix_level ---

def test_classify_vix_level_low():
    assert classify_vix_level(12.5) == "low"


def test_classify_vix_level_low_upper_boundary():
    assert classify_vix_level(14.99) == "low"


def test_classify_vix_level_normal_lower_boundary():
    assert classify_vix_level(15.0) == "normal"


def test_classify_vix_level_normal():
    assert classify_vix_level(17.0) == "normal"


def test_classify_vix_level_normal_upper_boundary():
    assert classify_vix_level(19.99) == "normal"


def test_classify_vix_level_elevated_lower_boundary():
    assert classify_vix_level(20.0) == "elevated"


def test_classify_vix_level_elevated():
    assert classify_vix_level(25.0) == "elevated"


def test_classify_vix_level_elevated_upper_boundary():
    assert classify_vix_level(30.0) == "elevated"


def test_classify_vix_level_crisis_lower_boundary():
    assert classify_vix_level(30.01) == "crisis"


def test_classify_vix_level_crisis():
    assert classify_vix_level(35.0) == "crisis"


# --- write_json ---

def test_write_json_creates_file_with_correct_content():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "out.json")
        data = {"date": "2026-06-19", "spy_ema": "bullish", "vix": 18.4}
        write_json(data, path)
        with open(path) as f:
            result = json.load(f)
        assert result == data


def test_write_json_creates_parent_dirs():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "nested", "deep", "out.json")
        write_json({"x": 1}, path)
        assert os.path.exists(path)
```

- [ ] **Step 3: Run tests to verify they all fail (module not found)**

```bash
pytest tests/test_fetch_market_data.py -v
```

Expected: `ModuleNotFoundError: No module named 'fetch_market_data'`

- [ ] **Step 4: Create `fetch_market_data.py` with classification functions and write_json**

```python
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
```

- [ ] **Step 5: Run tests to verify they all pass**

```bash
pytest tests/test_fetch_market_data.py -v
```

Expected: 13 tests PASSED.

- [ ] **Step 6: Commit**

```bash
git add fetch_market_data.py tests/
git commit -m "feat: add EMA signal and VIX classification with tests"
```

---

## Task 3: Data Fetching + Main Entry Point

Add the yfinance calls and `main()` to complete the script.

**Files:**
- Modify: `fetch_market_data.py`

- [ ] **Step 1: Append `get_spy_ema_signal`, `get_vix_data`, and `main` to `fetch_market_data.py`**

Add the following below the existing `write_json` function:

```python
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
    vix_df = yf.download("^VIX", period="5d", interval="1d", progress=False)
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
```

- [ ] **Step 2: Run existing tests to confirm nothing broke**

```bash
pytest tests/test_fetch_market_data.py -v
```

Expected: 13 tests PASSED.

- [ ] **Step 3: Run the script manually to verify real data is fetched**

```bash
python fetch_market_data.py
```

Expected output (values will vary):
```
Written: {'date': '2026-06-19', 'spy_ema': 'bullish', 'spy_10ema': 534.21, 'spy_20ema': 529.87, 'vix': 18.4, 'vix_level': 'normal'}
```

- [ ] **Step 4: Verify `data/latest.json` was written**

```bash
cat data/latest.json
```

Expected:
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

- [ ] **Step 5: Commit**

```bash
git add fetch_market_data.py data/latest.json
git commit -m "feat: add yfinance data fetching and main entry point"
```

---

## Task 4: Dashboard HTML

**Files:**
- Create: `index.html`

- [ ] **Step 1: Write `index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Daily Market Dashboard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0f0f0f;
      color: #e0e0e0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', monospace;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 2rem;
    }
    h1 {
      font-size: 1.1rem;
      font-weight: 400;
      color: #555;
      margin-bottom: 2rem;
      letter-spacing: 0.15em;
      text-transform: uppercase;
    }
    .cards {
      display: flex;
      gap: 1.5rem;
      flex-wrap: wrap;
      justify-content: center;
    }
    .card {
      background: #1a1a1a;
      border: 1px solid #2a2a2a;
      border-radius: 12px;
      padding: 2rem 2.5rem;
      min-width: 220px;
      text-align: center;
    }
    .card-title {
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.2em;
      color: #555;
      margin-bottom: 1rem;
    }
    .card-label {
      font-size: 2.5rem;
      font-weight: 700;
      letter-spacing: 0.05em;
      margin-bottom: 0.75rem;
    }
    .card-sub { font-size: 0.8rem; color: #555; }
    .bullish  { color: #22c55e; }
    .bearish  { color: #ef4444; }
    .low      { color: #22c55e; }
    .normal   { color: #eab308; }
    .elevated { color: #f97316; }
    .crisis   { color: #ef4444; }
    .unavailable { color: #333; }
    #date-line {
      margin-top: 2.5rem;
      font-size: 0.7rem;
      color: #333;
      text-transform: uppercase;
      letter-spacing: 0.1em;
    }
  </style>
</head>
<body>
  <h1>Market Dashboard</h1>

  <div class="cards" id="cards">
    <div class="card">
      <div class="card-title">Market Direction</div>
      <div class="card-label unavailable">—</div>
      <div class="card-sub">Loading...</div>
    </div>
    <div class="card">
      <div class="card-title">Volatility</div>
      <div class="card-label unavailable">—</div>
      <div class="card-sub">Loading...</div>
    </div>
  </div>

  <div id="date-line"></div>

  <script>
    async function loadData() {
      try {
        const res = await fetch('data/latest.json');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const d = await res.json();
        render(d);
      } catch {
        renderError();
      }
    }

    function render(d) {
      const emaClass = d.spy_ema === 'bullish' ? 'bullish' : 'bearish';
      document.getElementById('cards').innerHTML = `
        <div class="card">
          <div class="card-title">Market Direction</div>
          <div class="card-label ${emaClass}">${d.spy_ema.toUpperCase()}</div>
          <div class="card-sub">10EMA: ${d.spy_10ema} &nbsp;|&nbsp; 20EMA: ${d.spy_20ema}</div>
        </div>
        <div class="card">
          <div class="card-title">Volatility</div>
          <div class="card-label ${d.vix_level}">${d.vix_level.toUpperCase()}</div>
          <div class="card-sub">VIX: ${d.vix}</div>
        </div>
      `;
      document.getElementById('date-line').textContent = `Last updated: ${d.date}`;
    }

    function renderError() {
      document.getElementById('cards').innerHTML = `
        <div class="card">
          <div class="card-title">Market Direction</div>
          <div class="card-label unavailable">—</div>
          <div class="card-sub">Data unavailable</div>
        </div>
        <div class="card">
          <div class="card-title">Volatility</div>
          <div class="card-label unavailable">—</div>
          <div class="card-sub">Data unavailable</div>
        </div>
      `;
    }

    loadData();
  </script>
</body>
</html>
```

- [ ] **Step 2: Serve locally and verify the dashboard renders correctly**

```bash
python -m http.server 8000
```

Open `http://localhost:8000` in a browser.

Expected:
- Dark background, two cards side by side
- Card 1 shows `BULLISH` (green) or `BEARISH` (red) with EMA values beneath
- Card 2 shows `LOW` / `NORMAL` / `ELEVATED` / `CRISIS` with VIX value beneath
- Date line at the bottom showing today's date
- No console errors

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "feat: add dashboard HTML with two market indicator cards"
```

---

## Task 5: GitHub Actions Workflow

**Files:**
- Create: `.github/workflows/daily_update.yml`

- [ ] **Step 1: Create the workflow directory**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Write `.github/workflows/daily_update.yml`**

```yaml
name: Daily Market Update

on:
  schedule:
    - cron: '0 11 * * 1-5'  # 6am ET, weekdays
  workflow_dispatch:          # allows manual trigger from GitHub UI

permissions:
  contents: write

jobs:
  update:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Fetch market data
        run: python fetch_market_data.py

      - name: Commit data if changed
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/latest.json
          git diff --staged --quiet || git commit -m "data: update market indicators [skip ci]"
          git push
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/daily_update.yml
git commit -m "ci: add daily market data update workflow"
```

---

## Task 6: GitHub Pages Setup + Live Test

- [ ] **Step 1: Create a new GitHub repository**

Go to https://github.com/new and create a repo named `daily_dashboard` (public, no README).

- [ ] **Step 2: Push the local repo to GitHub**

```bash
git remote add origin https://github.com/<your-username>/daily_dashboard.git
git branch -M main
git push -u origin main
```

Replace `<your-username>` with your GitHub username.

- [ ] **Step 3: Enable GitHub Pages**

In the GitHub repo:
- Go to **Settings → Pages**
- Under **Source**, select `Deploy from a branch`
- Branch: `main`, folder: `/ (root)`
- Click **Save**

Expected: GitHub shows "Your site is published at `https://<username>.github.io/daily_dashboard/`" within ~1 minute.

- [ ] **Step 4: Trigger the workflow manually to confirm it runs**

In the GitHub repo:
- Go to **Actions → Daily Market Update**
- Click **Run workflow → Run workflow**

Expected:
- Workflow completes in ~30 seconds
- A new commit appears: `data: update market indicators [skip ci]`
- `data/latest.json` on the `main` branch is updated

- [ ] **Step 5: Open the live dashboard**

Visit `https://<username>.github.io/daily_dashboard/`

Expected: Same two-card layout as local, with today's live data.
