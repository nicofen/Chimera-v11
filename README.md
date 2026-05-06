# Project Chimera v11

> **Automated multi-asset trading system built on an async agent architecture.**  
> Trades stocks, crypto, forex, and futures through Alpaca — with AI-powered news filtering, regime-aware signal gating, real-time alerts, and a bias-corrected backtester.

<img width="916" height="672" alt="image" src="https://github.com/user-attachments/assets/4d749a46-11db-4d49-a5fe-012f52018885" />

---

## ⚠️ Risk Disclaimer

Past results do not predict future performance. Always paper-trade for a minimum of **3 months** before touching real capital. Never risk money you cannot afford to lose entirely. This software is provided for educational purposes.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [How It Works — Simple Version](#how-it-works--simple-version)
3. [Architecture — Technical Version](#architecture--technical-version)
4. [Module Reference](#module-reference)
   - [Mainframe](#mainframe)
   - [DataAgent](#dataagent)
   - [NewsAgent](#newsagent)
   - [StrategyAgent](#strategyagent)
   - [RiskAgent](#riskagent)
   - [OrderManager (OMS)](#ordermanager-oms)
   - [CircuitBreaker](#circuitbreaker)
   - [RegimeClassifier](#regimeclassifier)
   - [Social Intelligence](#social-intelligence)
   - [AlertSystem](#alert-system)
   - [Backtester](#backtester)
   - [Monte Carlo](#monte-carlo)
5. [Configuration Reference](#configuration-reference)
6. [Backtesting Guide](#backtesting-guide)
7. [Known Issues & Suggested Fixes](#known-issues--suggested-fixes)
8. [Lookahead Bias Audit](#lookahead-bias-audit)

---

## Quick Start

```bash
# 1. Clone and create a virtual environment
python -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your .env file (NEVER commit this file)
cat > .env << EOF
ALPACA_KEY=your_alpaca_key
ALPACA_SECRET=your_alpaca_secret
OPENAI_API_KEY=your_openai_key
WHALE_ALERT_KEY=your_whale_key     # optional
DUNE_API_KEY=your_dune_key         # optional
TELEGRAM_BOT_TOKEN=your_token      # optional
DISCORD_WEBHOOK_URL=your_url       # optional
CHIMERA_MODE=paper                 # ALWAYS start here
EOF

# 4. Launch
python -m chimera.mainframe
```

**Required API keys:** Alpaca (broker), OpenAI (news NLP).  
**Optional:** Whale Alert (BTC on-chain), Dune Analytics (SOL memecoins), Telegram/Discord (alerts).

---

## How It Works — Simple Version

Chimera is a fully automated trading bot. Here's what happens from market open to trade close:

**1. It watches the markets.**  
Price data for stocks, crypto, forex, and futures streams in every second via WebSocket. Chimera keeps a rolling 500-bar history per symbol.

**2. It reads the news every 30 seconds.**  
An AI (GPT-4o-mini) reads financial headlines. If it spots a major macro event — Fed meeting, inflation report, jobs data — it raises a **veto flag** and all trading pauses for 10 minutes. This protects against the violent, unpredictable price swings that happen around those events.

**3. It detects the market regime.**  
Every 15 minutes, a classifier looks at trend strength (ADX), EMA alignment, and volatility across all symbols. It decides whether the market is in a bull trend, bear trend, high volatility, or ranging. This controls which strategies are even allowed to fire — for example, long squeeze trades are blocked in a bear regime.

**4. It looks for opportunities.**  
The Strategy Agent runs four playbooks simultaneously:
- **Stocks:** Looks for short squeeze candidates using a score that combines short interest, volume surge, and social media mentions.
- **Crypto:** Watches Bitcoin whale activity and Solana memecoin volume for risk-on/risk-off signals.
- **Forex:** Uses AI sentiment + EMA momentum to trade USD direction.
- **Futures:** Looks for mean reversion around the Value Area (price zones where most volume traded).

**5. It calculates how much to bet.**  
Before any order is placed, the Risk Agent uses the Kelly Criterion — a mathematical formula that calculates optimal bet size based on your historical win rate. It's capped at 2% of your account per trade. The size is also scaled by the AI news confidence score.

**6. It runs seven safety checks.**  
Every order goes through a pre-flight checklist: Is the market open? Do we already have this position? Is the stop-loss in the right place? Is there enough equity? If any check fails, the order is rejected.

**7. It places a bracket order.**  
The order goes to Alpaca with the entry price, stop-loss, and take-profit already baked in. Alpaca manages the exit legs automatically.

**8. It protects the account with a circuit breaker.**  
Three independent trip conditions watch for catastrophic loss: daily loss limit (5%), peak drawdown (10%), or four losses in a row. Any one of these triggers an emergency close of all positions and halts new trading.

**9. It sends you alerts.**  
Every significant event — fills, stops hit, circuit breaker trips, daily summary — is sent to Telegram and/or Discord in real time.

---

## Architecture — Technical Version

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SHARED STATE                                   │
│  NewsState · MarketData · TechnicalSignals · RiskParameters · RegimeState   │
│  asyncio.Queue (signal_queue) · asyncio.Queue (order_queue)                 │
└──────────────────────┬──────────────────────────────────────────────────────┘
                       │  All agents communicate exclusively through SharedState
   ┌───────────────────┼──────────────────────────────────────────────────┐
   │                   │                                                  │
   ▼                   ▼                                                  ▼
DataAgent           NewsAgent                                    RegimeClassifier
 ├─ Alpaca WS        ├─ FinancialJuice REST                       ├─ ADX cross-symbol
 ├─ Crypto WS        ├─ Stocktwits trending                       ├─ EMA ribbon breadth
 ├─ Whale Alert      ├─ GPT-4o-mini LangChain                     ├─ ATR/price vix proxy
 ├─ Finviz screener  ├─ Regex veto patterns                       └─ 15-min interval
 ├─ Dune Analytics   └─ veto_active → SharedState
 └─ Alpaca futures                    │
                                      │ vetoes signals
                                      ▼
                              StrategyAgent
                               ├─ Sector A: Crypto regime
                               ├─ Sector B: Stock squeeze (Sp score)
                               ├─ Sector C: Forex NLP momentum
                               ├─ Sector D: Futures AVWAP mean-rev
                               └─ Regime gate → signal_queue
                                              │
                                              ▼
                                        RiskAgent
                                         ├─ Kelly Criterion sizing
                                         ├─ ATR × 2 stop / ATR × 3 TP
                                         ├─ news_multiplier scalar
                                         └─ order_queue
                                                │
                                                ▼
                                       OrderManager (OMS)
                                         ├─ PreflightChecker (7 gates)
                                         ├─ Alpaca bracket orders
                                         ├─ WebSocket fill tracking
                                         ├─ TrailingStopManager
                                         └─ TradeLogger (SQLite)
                                                │
                           ┌────────────────────┤
                           │                    │
                           ▼                    ▼
                    CircuitBreaker          AlertAgent
                     ├─ Daily loss           ├─ Signal alerts
                     ├─ Drawdown             ├─ Fill alerts
                     ├─ Loss streak          ├─ Close alerts
                     └─ force_close_all()    ├─ Veto changes
                                             ├─ Daily summary
                                             └─ AlertDispatcher
                                                 ├─ TelegramSender
                                                 └─ DiscordSender
```

<img width="825" height="878" alt="image" src="https://github.com/user-attachments/assets/fec08d63-e365-4271-b3b6-5d4741d85f7a" />


Every agent is an `asyncio.Task`. They **never call each other directly** — all communication passes through `SharedState`. This makes each agent independently testable and allows any one of them to be restarted without taking down the others.

---

## Module Reference

### Mainframe

**File:** `mainframe.py`

The top-level orchestrator. Creates one `SharedState` and passes it to every agent. Launches all agents as concurrent `asyncio.Task`s and handles graceful shutdown.

```python
from chimera.mainframe import Mainframe
from chimera.config.settings import load_config

mainframe = Mainframe(load_config())
asyncio.run(mainframe.run())
```

> **Bug (v11):** `Mainframe.__init__` references `self.dispatcher`, `self.alert_agent`, and `self.regime_classifier` in `run()` but never initialises them in `__init__`. This will crash on startup. See [Known Issues](#known-issues--suggested-fixes).

---

### DataAgent

**File:** `agents/data_agent.py`

Manages all inbound market data. Runs six coroutines concurrently:

| Coroutine | Source | Data written to state |
|---|---|---|
| `_alpaca_stocks_ws` | Alpaca WS (IEX) | `state.market.stocks[sym]` — OHLCV bars |
| `_alpaca_crypto_ws` | Alpaca Crypto WS | `state.market.crypto[sym]` — OHLCV bars |
| `_whale_alert_poll` | Whale Alert REST | `state.market.crypto["btc_exchange_inflow"]` |
| `_finviz_poll` | Finviz Python lib | `state.market.stocks[sym]["short_interest"]`, `["rvol"]` |
| `_dune_poll` | Dune Analytics REST | `state.market.crypto["sol_memecoin_vol_spike"]` |
| `_alpaca_futures_poll` | Alpaca REST | `state.market.futures[sym]` — OHLCV bars |

Each ingestor has auto-reconnect logic with a 5-second backoff. Bar windows are capped at 500 bars per symbol.

> **Note:** There is no forex data ingestor. `state.market.forex` will always be empty, meaning the forex strategy (`_sector_forex`) never fires. See [Known Issues](#known-issues--suggested-fixes).

---

### NewsAgent

**File:** `agents/news_agent.py`

Polls headlines every 30 seconds and classifies them using GPT-4o-mini via LangChain. The most important safety mechanism in the system.

**Pipeline:**
1. Fetch headlines from FinancialJuice + Stocktwits trending (capped at 20 headlines)
2. Fast regex scan for macro keywords (FOMC, CPI, NFP, rate decision). If matched → **veto immediately** without spending LLM tokens.
3. If no regex match → send to GPT-4o-mini. Parse JSON response for `sentiment`, `confidence`, `macro_event`.
4. If `macro_event: true` → veto. Otherwise, write sentiment to `state.news`.

**Veto effect:**  
`state.news.veto_active = True` causes:
- `StrategyAgent._emit()` to drop all signals
- `RiskAgent._process()` to drop all signals  
- `PreflightChecker._check_veto()` to reject all orders
- `state.news_multiplier()` to return `0.0`

The veto auto-clears after `veto_cooldown_seconds` (default: 600s / 10 minutes).

**News multiplier:**
```python
if sentiment == BULLISH:  return min(1.0, confidence * 1.1)
if sentiment == BEARISH:  return confidence * 0.5
else:                     return confidence  # neutral
```
This multiplier is applied to `risk_pct` in RiskAgent — bearish news halves position size.

---

### StrategyAgent

**File:** `agents/strategy_agent.py`

Runs on a configurable interval (default: 15 seconds). Evaluates all four sectors and emits `TechnicalSignals` to `state.signal_queue`.

#### Shared TA Helpers (`utils/ta.py`)

All indicators are vectorised with NumPy:

| Function | Description |
|---|---|
| `ema(prices, period)` | Exponential Moving Average |
| `rsi(prices, period=14)` | Relative Strength Index (simplified, not Wilder-smoothed) |
| `adx(high, low, close, period=14)` | Average Directional Index |
| `atr_value(high, low, close, period=14)` | Average True Range |
| `bollinger_squeeze(prices, period=20)` | Returns `(is_squeeze, bb_width)`. Squeeze when width < 2% |
| `detect_rsi_divergence(prices, rsi_arr, lookback=5)` | Price/RSI moving in opposite directions |

#### Sector A — Crypto

Uses on-chain data to determine regime, then applies standard TA:

```
if btc_exchange_inflow > threshold: regime = "risk_off" → direction = "flat"
if sol_memecoin_vol_spike AND risk_off: regime = "high_volatility_scalp" → direction = "long"
```

Underlying direction from `_build_signal()` is used if no regime override.

<img width="2781" height="3235" alt="image" src="https://github.com/user-attachments/assets/dafc71e1-336d-4daa-a2fc-83f3a990a86c" />

<img width="3141" height="3949" alt="image" src="https://github.com/user-attachments/assets/d0b2ec61-498c-4eaf-8822-b90d0a6153ea" />

#### Sector B — Stocks (Squeeze Probability Score)

<img width="2487" height="2652" alt="image" src="https://github.com/user-attachments/assets/5976bbe1-4fb4-409d-931e-7a31d74ea1af" />

The core equity strategy. Calculates `Sp ∈ [0, 1]`:

```
Sp = (SI_norm × 0.4) + (RVOL_norm × 0.3) + (Z_norm × 0.3)

where:
  SI_norm   = min(short_interest / 0.50, 1.0)   # 50% SI → 1.0
  RVOL_norm = min((rvol - 1.0) / 9.0, 1.0)      # RVOL 1→10 maps to 0→1
  Z_norm    = min(max(social_zscore / 5.0, 0), 1.0)
```

- `Sp < 0.60` → signal dropped
- `Sp > 0.75` → direction forced to `"long"` regardless of TA

#### Sector C — Forex

Combines News Agent sentiment with EMA momentum:
- `BULLISH` news + price below `EMA(20)` → long
- Confidence scaled by `news_multiplier()`

#### Sector D — Futures (Value Area Mean Reversion)

Uses an anchored VWAP approximation:
```
AVWAP = cumulative(close × volume) / cumulative(volume)
VAH = AVWAP × 1.002  (Value Area High)
VAL = AVWAP × 0.998  (Value Area Low)

price ≤ VAL → long (mean-revert up)
price ≥ VAH → short (mean-revert down)
```
Confidence is fixed at `0.75` for value-area signals.

<img width="2782" height="3235" alt="image" src="https://github.com/user-attachments/assets/a179031f-0766-498c-9f53-91c0f4d12c47" />


#### Signal Emission Gate

Before any signal reaches the queue, three gates are checked in order:
1. **Circuit breaker** — `state.circuit_open` → drop
2. **News veto** — `state.is_vetoed()` → drop
3. **Regime gate** — `is_signal_allowed(regime, sector, direction)` → drop if not permitted

---

### RegimeClassifier

**File:** `regime/classifier.py` and `regime/models.py`

Runs every 15 minutes (configurable). Classifies the overall market regime by aggregating signals across all symbols and sectors.

#### Classification Rules (applied in priority order)

| Priority | Condition | Regime |
|---|---|---|
| 1 | ATR/price > 2.5% (VIX proxy) | `HIGH_VOLATILITY` |
| 2 | ADX > 25 AND >50% symbols EMA-bull AND breadth > 60% | `TRENDING_BULL` |
| 3 | ADX > 25 AND >50% symbols EMA-bear AND breadth < 40% | `TRENDING_BEAR` |
| 4 | ADX < 20 | `MEAN_REVERTING` |
| 5 | Everything else | `NEUTRAL` |

**Smoothing:** A new regime must be detected for `smoothing_periods` (default: 3) consecutive evaluations before being committed to `SharedState`. This prevents rapid regime flipping on short-term noise.

#### Regime Permission Matrix

Each regime restricts which sector/direction combinations are allowed:

| Regime | Stocks | Crypto | Forex | Futures |
|---|---|---|---|---|
| TRENDING_BULL | long | long | both | long |
| TRENDING_BEAR | short | none | short | short |
| HIGH_VOLATILITY | none | both | none | none |
| MEAN_REVERTING | none | none | both | both |
| NEUTRAL | both | both | both | both |

Signals that violate this matrix are dropped by `StrategyAgent._emit()` before reaching the queue.

---

### RiskAgent

**File:** `agents/risk_agent.py`

Consumes `TechnicalSignals` from `state.signal_queue` and emits `RiskParameters` to `state.order_queue`.

#### Position Sizing Formula

```
Position Size = (Equity × risk%) / (ATR × ATR_MULTIPLIER)

where:
  risk% = min(base_risk_pct, MAX_RISK_PER_TRADE=2%, kelly_fraction)
  risk% ×= news_multiplier()      # scales with news sentiment
  risk% ×= signal.confidence      # scales with TA conviction
```

#### Kelly Criterion

```
f* = (b × p − q) / b

where:
  b = avg_win_R / avg_loss_R    (configured, default 1.5 / 1.0)
  p = win_rate from last N trades (default lookback: 50 trades)
  q = 1 - p

Capped at MAX_KELLY_FRACTION = 25%
Falls back to 10% until 10+ trades are recorded
```

#### Stop-Loss and Take-Profit

```
Long:   stop  = entry − ATR × 2.0
        tp    = entry + ATR × 3.0     (1.5:1 reward:risk)

Short:  stop  = entry + ATR × 2.0
        tp    = entry − ATR × 3.0
```

Entry price is estimated from the latest close in state (actual fill price set by Alpaca on execution).

---

### OrderManager (OMS)
<img width="807" height="535" alt="image" src="https://github.com/user-attachments/assets/35257815-2d30-4769-88af-97fc432301a5" />

**File:** `oms/order_manager.py`

The executor layer. Runs three concurrent loops:

1. **`_consume_order_queue`** — pulls `RiskParameters`, runs pre-flight checks, submits bracket orders to Alpaca.
2. **`_stream_order_updates`** — listens to Alpaca's WebSocket for fill events (`fill`, `partial_fill`, `canceled`, `rejected`).
3. **`_trailing_stop_loop`** — every 10 seconds, checks unrealised P&L on all open positions and ratchets stops.

#### Pre-flight Checks (`oms/preflight.py`)

All seven must pass or the order is rejected and logged:

| Check | What it verifies |
|---|---|
| Veto | `state.news.veto_active` must be False |
| Duplicate | No existing open position in the same symbol |
| Position limit | Open positions < `max_open_positions` (default: 5) |
| Qty positive | `order.qty > 0` |
| Stop sanity | Stop on correct side of entry; distance ≤ 5× ATR |
| Market hours | Stocks must be within 09:30–16:00 ET Mon–Fri (configurable) |
| Equity sufficient | Trade risk ≤ per-trade max AND ≤ remaining daily budget |

#### Bracket Order Structure

```json
{
  "symbol": "GME",
  "qty": "10.0",
  "side": "buy",
  "type": "market",
  "order_class": "bracket",
  "stop_loss": { "stop_price": "15.50" },
  "take_profit": { "limit_price": "18.75" }
}
```

Alpaca manages the child legs — when either the stop or TP fills, the other is automatically cancelled.

#### Trailing Stop Logic (`oms/trailing_stop.py`)

Three-stage ratchet for longs (mirrored for shorts):

| Stage | Condition | Stop behaviour |
|---|---|---|
| Initial | R < 1.0 | ATR-trail at `price − ATR × 2` |
| Breakeven | R ≥ 1.0 | Stop never below fill price |
| Profit lock | R ≥ 2.0 | Stop never below `fill + 0.5 × lock_r × risk` |

Stop only ever moves in your favour — never widened.

#### Trade Logging (`oms/trade_logger.py`)
<img width="799" height="337" alt="image" src="https://github.com/user-attachments/assets/641b1177-3d64-4cd1-b4e1-cda933e3051c" />


Every order lifecycle event is persisted to SQLite (`chimera_trades.db`). Tables: `orders`, `breaker_events`.

---

### CircuitBreaker

**File:** `risk/circuit_breaker.py`

Evaluates three independent trip conditions every 5 seconds.

#### Trip Conditions

| Condition | Default threshold | Auto-reset |
|---|---|---|
| Daily loss | 5% of start-of-day equity | Midnight UTC |
| Peak-to-trough drawdown | 10% from high-water mark | **Manual only** |
| Consecutive loss streak | 4 losses in a row | First win or manual reset |

**Daily loss** includes unrealised P&L from open positions — the breaker fires before a bad trade fully closes.

#### Trip Action
<img width="816" height="344" alt="image" src="https://github.com/user-attachments/assets/489b671a-84e6-46b0-ad7b-a21b8821e7c1" />

When any condition fires:
1. `state.circuit_open = True` → signals and orders blocked immediately
2. `OMS.force_close_all()` → all positions liquidated at market
3. Event persisted to `breaker_events` SQLite table
4. Alert sent via `AlertDispatcher`
5. State transitions to `COOLDOWN` — requires manual reset

#### Manual Reset

```bash
# REST API
curl -X POST "http://localhost:8765/api/breaker/reset?note=investigated+ok"

# Python
breaker.reset("root cause identified, resuming")
```

---

### Social Intelligence

**Files:** `social/zscore.py`, `social/sentiment.py`, `social/scraper.py`, `social/monitor.py`

#### Z-Score Engine (`social/zscore.py`)

<img width="848" height="315" alt="image" src="https://github.com/user-attachments/assets/45f8aeb4-5f91-4f52-b359-ef59c9b9292d" />

Tracks the abnormality of social mention rates per symbol:

```
Z = (current_5m_count − μ_baseline) / σ_baseline
```

- **Baseline:** 10-minute snapshots over 24 hours (minimum 6 snapshots required)
- **Spike threshold:** Z ≥ 2.0
- **Normalization for Sp formula:** `Z / 5.0`, clipped to `[0, 1]`

Thread-safe via `threading.RLock`. Mentions expire automatically after 24 hours.

#### Sentiment Tagger (`social/sentiment.py`)

Two-stage pipeline per message:
1. **API tag** — if the Stocktwits poster explicitly tagged `$bullish` or `$bearish`, use that directly (confidence: 0.85).
2. **Keyword fallback** — weighted regex lexicon of bullish/bearish terms (emoji included). Bull-ratio ≥ 0.60 → bullish, ≤ 0.40 → bearish.

#### Live Monitor

```bash
python -m chimera.social.monitor --symbols GME AMC TSLA
```

---

### Alert System

**Files:** `alerts/dispatcher.py`, `alerts/agent.py`, `alerts/models.py`, `alerts/telegram_sender.py`, `alerts/discord_sender.py`

#### AlertDispatcher

Central notification hub. Rate-limits by priority tier:

| Priority | Throttle |
|---|---|
| CRITICAL | Never throttled |
| HIGH | 1 per 30 seconds |
| NORMAL | 1 per 60 seconds |
| LOW | 1 per 300 seconds |

Consecutive identical event types within the window are deduplicated.

#### AlertAgent

Polls `SharedState` every 5 seconds and fires events for:
- New signals emitted (up to 3 per tick)
- New fills
- Closed positions (P&L + R-multiple)
- Veto raised / cleared
- Daily loss or drawdown approaching 80% of limit (early warning)
- Daily summary at midnight
- Periodic heartbeat (default: hourly)

#### Event Types

`SIGNAL_EMITTED`, `ORDER_FILLED`, `POSITION_CLOSED`, `VETO_RAISED`, `VETO_CLEARED`, `CIRCUIT_TRIPPED`, `CIRCUIT_RESET`, `DAILY_LOSS_WARN`, `DRAWDOWN_WARN`, `DAILY_SUMMARY`, `HEARTBEAT`

---

### Backtester
<img width="840" height="397" alt="image" src="https://github.com/user-attachments/assets/2e6bc76f-c1fc-45fe-92a6-0d0f4e33ea9a" />

**Files:** `backtest/engine.py`, `backtest/simulated_oms.py`, `backtest/data_loader.py`, `backtest/performance.py`

The backtester reuses `StrategyAgent` and `RiskAgent` verbatim — identical code to live trading. Only the OMS is swapped for `SimulatedOMS`.

#### Six Bias Corrections

| Fix | Bias | Solution |
|---|---|---|
| FIX 1 | Same-bar fill | Orders stamped `dt + 1s`; fill guard requires `queued_dt < bar_dt` |
| FIX 2 | Full-Kelly sizing | `_kelly_fraction()` patched to return `× 0.5` |
| FIX 3 | Optimistic slippage | Stocks: 25 bps, Crypto: 30 bps, Forex: 5 bps, Futures: 3 bps |
| FIX 4 | Stale SI / RVOL | Historical dicts injected per bar; non-zero fallback (10% SI, 1.5× RVOL) |
| FIX 5 | Missing news veto | Event calendar replayed; built-in FOMC/NFP blackout dates 2010–2030 |
| FIX 6 | Per-symbol warmup | Global warmup: no signals until ALL symbols clear 200-bar threshold |

#### SimulatedOMS Fill Logic

- **Market entries:** Fill at next bar's open + slippage
- **Stop-loss:** If bar gaps through stop, fill at open (gap risk, realistic)
- **Take-profit:** Fill at exact TP price if bar's high/low reaches it
- **Trailing stop:** Ratcheted on each bar close, checked against next bar

#### Data Loader (`backtest/data_loader.py`)

Tries three sources in order:
1. Local Parquet cache (instant on repeat runs)
2. Local CSV file
3. Alpaca REST API (with pagination; caches to Parquet after first download)

```bash
# Run a backtest
python -m chimera.backtest.run_backtest \
    --sector stocks \
    --symbols GME AMC TSLA \
    --start 2022-01-01 --end 2024-01-01 \
    --equity 100000

# Python API
from chimera.backtest.engine import BacktestEngine
engine = BacktestEngine(load_config())
report = engine.run(
    symbols={"stocks": ["GME", "AMC"], "crypto": ["BTC/USD"]},
    start="2022-01-01", end="2024-01-01",
)
report.print_summary()
```

---

### Monte Carlo

**File:** `backtest/monte_carlo.py`

Stress-tests backtest results by resampling the actual trade P&L sequence N times (default: 10,000).

**Two modes:**
- **Bootstrap** (default): Draw N trades with replacement. Preserves P&L distribution, scrambles order.
- **Block bootstrap**: Draw consecutive blocks of K trades. Preserves win/loss streak autocorrelation.

**Aggregate outputs:**
- Equity percentile bands (5th, 10th, 25th, 50th, 75th, 90th, 95th)
- Ruin probability (equity falls below configurable threshold)
- Probability of profit at T trades
- Median max drawdown and CVaR (expected shortfall at 5%)

```bash
python -m chimera.backtest.run_monte_carlo --help
```

---

## Configuration Reference

All settings are loaded from environment variables or `.env`. Override any value by setting the env var before launch.

| Variable | Default | Description |
|---|---|---|
| `CHIMERA_MODE` | `paper` | `paper` or `live` |
| `ALPACA_KEY` | required | Alpaca API key |
| `ALPACA_SECRET` | required | Alpaca API secret |
| `OPENAI_API_KEY` | required | OpenAI key for news NLP |
| `WHALE_ALERT_KEY` | `""` | Whale Alert API key (optional) |
| `DUNE_API_KEY` | `""` | Dune Analytics key (optional) |
| `TELEGRAM_BOT_TOKEN` | `""` | Telegram bot token (optional) |
| `TELEGRAM_CHAT_ID` | `""` | Telegram chat ID (optional) |
| `DISCORD_WEBHOOK_URL` | `""` | Discord webhook URL (optional) |
| `CB_DAILY_LOSS_PCT` | `0.05` | Circuit breaker daily loss limit (5%) |
| `CB_DRAWDOWN_PCT` | `0.10` | Circuit breaker drawdown limit (10%) |
| `CB_STREAK_LIMIT` | `4` | Consecutive loss streak limit |
| `REGIME_ADX_TREND` | `25.0` | ADX threshold for trending regime |
| `REGIME_ADX_RANGE` | `20.0` | ADX threshold for ranging regime |
| `REGIME_VIX_PROXY` | `0.025` | ATR/price ratio for high-vol regime |
| `REGIME_UPDATE_MIN` | `15` | Minutes between regime updates |
| `REGIME_SMOOTH` | `3` | Smoothing periods before regime commit |
| `CHIMERA_API_HOST` | `0.0.0.0` | Dashboard API host |
| `CHIMERA_API_PORT` | `8765` | Dashboard API port |

---

## Known Issues & Suggested Fixes

### 🔴 HIGH — Mainframe crashes on startup

**Location:** `mainframe.py`, `Mainframe.__init__` and `Mainframe.run()`

**Problem:** `run()` references `self.dispatcher`, `self.alert_agent`, and `self.regime_classifier`, but none of these are initialised in `__init__`. The system crashes immediately with `AttributeError`.

**Fix:**
```python
# Add to Mainframe.__init__():
self.dispatcher       = build_dispatcher(config)
self.circuit_breaker  = CircuitBreaker(self.state, self.order_manager, config,
                                       dispatcher=self.dispatcher)
self.alert_agent      = AlertAgent(self.state, self.dispatcher, config)
self.regime_classifier = RegimeClassifier(self.state, config)
```

---

### 🔴 HIGH — `_TradeOutcome` objects crash `RiskAgent`

**Location:** `oms/order_manager.py`, `_close_position()`

**Problem:** After a trade closes, OMS posts a `_TradeOutcome` object to `state.signal_queue`. The `RiskAgent` reads from this same queue and calls `self._process(signal)`, which expects a `TechnicalSignals` object. Accessing `.confidence` on a `_TradeOutcome` raises `AttributeError` and crashes the RiskAgent loop.

**Fix:** Add a separate `outcome_queue` to `SharedState` and have the circuit breaker watch it, or add a type check in `RiskAgent._process()`:
```python
async def _process(self, signal) -> None:
    if hasattr(signal, "won"):   # _TradeOutcome — route to Kelly updater
        self.record_trade_outcome(signal.won)
        return
    # ... existing logic
```

---

### 🔴 HIGH — Forex strategy is permanently dead

**Location:** `agents/data_agent.py`

**Problem:** There is no forex data ingestor in `DataAgent`. `state.market.forex` is always empty, so `StrategyAgent._sector_forex()` returns immediately every cycle. The forex strategy never fires.

**Fix:** Add a forex WebSocket or REST poller. Alpaca provides forex data via their streaming API:
```python
async def _alpaca_forex_ws(self) -> None:
    # Subscribe to forex bars for configured pairs
    symbols = self.config.get("forex_pairs", ["EUR/USD"])
    # Use Alpaca's forex stream endpoint
```

---

### 🟡 MEDIUM — `state.signals` list grows unbounded

**Location:** `utils/state.py`, `SharedState.put_signal()`

**Problem:** `state.signals` is a plain list with no maximum size. `OMS._build_order()` iterates `reversed(self.state.signals)` on every order to find the latest signal for a symbol — this is O(n) and grows slower over hours/days of trading. After 24 hours of continuous running, the list could contain tens of thousands of entries.

**Fix:**
```python
from collections import deque
self.signals: deque[TechnicalSignals] = deque(maxlen=1000)
```

---

### 🟡 MEDIUM — RSI uses simplified formula (not Wilder-smoothed)

**Location:** `utils/ta.py`, `rsi()`

**Problem:** The RSI implementation uses `np.mean(gains[-period:])` — a simple rolling average. The industry-standard Wilder smoothing uses an exponential moving average. Values will differ from TradingView, Bloomberg, and most charting platforms, which can cause signals to diverge from what a human analyst would see.

**Fix:**
```python
def rsi(prices: np.ndarray, period: int = 14) -> float:
    deltas = np.diff(prices)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    # Wilder smoothing: seed with SMA, then EMA
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))
```

---

### 🟡 MEDIUM — Circuit breaker loss streak counter is unreliable

**Location:** `risk/circuit_breaker.py`, `_update_loss_streak()`

**Problem:** The streak counter uses `len(state.risk_params)` as a proxy for the number of closed trades, then iterates `state.signals` to find `_TradeOutcome` objects. These two lists are completely independent — `risk_params` grows with every accepted order (not every closed trade), and `signals` now grows unboundedly. The counter can miss trades under load.

**Fix:** Maintain an explicit `state.closed_trades` counter or a dedicated `outcome_queue` as described above.

---

### 🟠 LOW — No rate-limit handling on REST polls

**Location:** `agents/data_agent.py`, `_whale_alert_poll()`, `_dune_poll()`, `_finviz_poll()`

**Problem:** HTTP 429 responses are caught by the generic `except Exception` handler and logged as warnings, but the poll immediately retries on the next interval with no backoff. Under rate-limit conditions this creates a flood of failed requests and silently drops data.

**Fix:** Add exponential backoff:
```python
except aiohttp.ClientResponseError as e:
    if e.status == 429:
        await asyncio.sleep(min(interval * 2, 300))
    else:
        log.warning(f"Poll error: {e}")
```

---

### 🟠 LOW — `_build_order` uses forward-scan for signal lookup

**Location:** `oms/order_manager.py`, `_build_order()`

**Problem:** When building an order, the OMS searches `self.state.signals` using `next((s.sector for s in self.state.signals if s.symbol == rp.symbol), "unknown")`. This forward-scans from the oldest signal — it should search in reverse to get the most recent signal for the symbol. The `reversed()` call in `SimulatedOMS` is correct; the live OMS is inconsistent.

**Fix:**
```python
sector = next(
    (s.sector for s in reversed(self.state.signals) if s.symbol == rp.symbol),
    "unknown",
)
```

---

## Lookahead Bias Audit

Lookahead bias occurs when a backtest uses information that would not have been available at the time a trading decision was made. This section documents every potential source and its current status.

### ✅ FIX 1 — Same-bar fill (RESOLVED)

**Risk:** Signal generated on bar N's close fills on bar N at bar N's open — using a price that was in the future relative to when the signal was computed.

**Resolution:** Orders are stamped `dt + 1 second`. The fill guard checks `queued_dt < bar_dt`, which is only true on bar N+1. Signals always fill at the *next* bar's open, not the current bar.

---

### ✅ FIX 2 — Full-Kelly in backtest (RESOLVED)

**Risk:** Using the full Kelly fraction in simulation produces unrealistically aggressive sizing. Real execution introduces drawdowns that would cause a rational trader to reduce size.

**Resolution:** The `_kelly_fraction()` method is monkey-patched to return `× 0.5` (half-Kelly). This is a well-established industry convention that accounts for model uncertainty.

---

### ✅ FIX 3 — Optimistic slippage defaults (RESOLVED)

**Risk:** Backtests with 2–5 bps slippage on momentum stocks (where you are often the market) massively overstate profitability. Real market impact on GME-style names can be 25–50 bps per side.

**Resolution:** Defaults raised to: Stocks 25 bps, Crypto 30 bps, Forex 5 bps, Futures 3 bps. These are conservative mid-range values from academic literature on retail momentum strategies.

---

### ✅ FIX 4 — Stale short-interest / RVOL data (RESOLVED)

**Risk:** If `short_interest` and `rvol` are not injected per bar, they default to `0.0`, making `Sp = 0.0` for all stocks in backtests (no signals would fire, or they all fire with the same stale value from Finviz).

**Resolution:** `BacktestEngine.run()` accepts `historical_si` and `historical_rvol` dicts keyed by `(symbol, date_str)` and injects them per bar. When no historical data is available, fallback values of `SI=10%` and `RVOL=1.5×` are used — non-zero defaults that produce realistic but conservative signals.

---

### ✅ FIX 5 — No news veto in backtest (RESOLVED)

**Risk:** Omitting the news veto means the backtest trades through FOMC and CPI dates — events where real Chimera would be in cash. This inflates apparent performance by assuming the system magically picked the right direction on high-uncertainty events.

**Resolution:** An `event_calendar` DataFrame can be passed to `BacktestEngine.run()`. If not provided, a built-in approximate calendar of FOMC and NFP dates (2010–2030) is used. Veto dates are replayed as `state.news.veto_active = True` for those bars.

---

### ✅ FIX 6 — Per-symbol warmup creates unequal starting points (RESOLVED)

**Risk:** If symbol A needs 200 bars to warm up its indicators and symbol B is added mid-run, symbol B starts trading on bar 1 with nonsensical indicator values (a 200-period EMA computed on 10 bars is meaningless).

**Resolution:** Global warmup mode (default): no signals are generated until **all** symbols in the run have accumulated at least `warmup_bars` bars. This ensures every indicator is properly seeded before trading begins.

---

### ⚠️ REMAINING RISK — ADX calculation uses simple convolution (not Wilder smoothing)

**Risk (low):** The `adx()` function uses `np.convolve(...) / period` (simple moving average) rather than Wilder's exponential smoothing. ADX values will be lower than chart platform equivalents, and the 25-threshold for trend detection may need recalibration.

**Impact:** Signals may fire earlier or later than they would with correct ADX. This is a systematic bias (consistent between backtest and live) so it does not cause backtest overfitting, but results may not match strategy descriptions based on standard ADX.

---

### ⚠️ REMAINING RISK — AVWAP resets at bar 0, not at session open

**Risk (low):** The futures Value Area calculation uses `np.cumsum()` starting from bar 0 of the available history, not from the actual session open (e.g. 09:30 ET for ES). Over a 200-bar window this creates an AVWAP that is anchored to an arbitrary point in the past, not the current session open.

**Impact:** Value Area High/Low levels will be wrong. In practice the code falls back to `avwap[-1] × 1.002` and `avwap[-1] × 0.998` which are reasonable approximations, but they don't represent the true session's value area.

**Suggested fix:** Filter bars to the current trading session before computing the cumsum.

---

### ⚠️ REMAINING RISK — Slippage model only applied at entry, not exit

**Risk (medium):** `SimulatedOMS._fill_entry()` applies slippage at entry. `SimulatedOMS._close()` fills at the exact stop or TP price with no exit slippage. In reality, both entries and exits incur market impact.

**Impact:** Overstates net P&L, especially for stop-loss exits on momentum stocks where the exit is at a disadvantageous market price.

**Suggested fix:** Apply slippage symmetrically in `_close()`:
```python
if order.side == OrderSide.BUY:   # exiting a long → sell at bid
    exit_fill = price * (1 - slippage_mult)
else:                             # exiting a short → buy at ask
    exit_fill = price * (1 + slippage_mult)
```

---

*This document was generated against Chimera v11. Always review the source files for the most current implementation.*
