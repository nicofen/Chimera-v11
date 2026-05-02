"""
chimera/backtest/monte_carlo.py
Monte Carlo simulator — stress-tests a completed backtest by resampling
the actual trade P&L sequence thousands of times and building a distribution
of possible equity paths.

Two resampling modes:
  1. Bootstrap (default)  — draw N trades with replacement from the real trade list.
     Preserves the actual P&L distribution but scrambles temporal order.
     Best for: "what range of outcomes was possible given this edge?"

  2. Block bootstrap       — draw consecutive blocks of K trades with replacement.
     Preserves short-run autocorrelation (win/loss streaks).
     Best for: strategies where streaks matter (trend-following, momentum).

Outputs per simulation run:
  - Full equity curve array
  - Terminal equity
  - Max drawdown
  - Sharpe ratio (annualised)
  - CAGR
  - Worst consecutive loss count

Aggregate outputs across N simulations:
  - Percentile bands: 5th, 10th, 25th, 50th, 75th, 90th, 95th
  - Ruin probability  (equity < ruin_threshold% of initial)
  - Probability of profit at T trades
  - Median max drawdown
  - Expected shortfall (CVaR at 5%)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class SimPath:
    """Single Monte Carlo run result."""
    terminal_equity:    float
    max_drawdown_pct:   float
    cagr_pct:           float
    sharpe:             float
    worst_streak:       int
    equity_curve:       list[float]   # sampled equity at each trade step


@dataclass
class MonteCarloResult:
    """Aggregate result across all N simulation paths."""
    n_simulations:      int
    n_trades:           int
    initial_equity:     float
    paths:              list[SimPath]  = field(repr=False)

    # ── Terminal equity percentiles ───────────────────────────────────────
    p05:  float = 0.0   # 5th  percentile terminal equity
    p10:  float = 0.0
    p25:  float = 0.0
    p50:  float = 0.0   # median
    p75:  float = 0.0
    p90:  float = 0.0
    p95:  float = 0.0   # 95th percentile terminal equity

    # ── Risk metrics ──────────────────────────────────────────────────────
    ruin_probability:   float = 0.0   # fraction of runs ending below ruin threshold
    prob_profit:        float = 0.0   # fraction of runs ending above initial equity
    median_max_dd:      float = 0.0   # median of max-drawdown distribution
    cvar_5pct:          float = 0.0   # Expected shortfall: mean of worst 5% terminal equities
    mean_terminal:      float = 0.0
    std_terminal:       float = 0.0

    # ── Per-percentile equity curves (for the fan chart) ─────────────────
    # Each is a list[float] of length n_trades+1 (one per trade step)
    curve_p05:  list[float] = field(default_factory=list)
    curve_p25:  list[float] = field(default_factory=list)
    curve_p50:  list[float] = field(default_factory=list)
    curve_p75:  list[float] = field(default_factory=list)
    curve_p95:  list[float] = field(default_factory=list)
    curve_original: list[float] = field(default_factory=list)  # actual historical path

    def summary(self) -> dict[str, Any]:
        return {
            "n_simulations":    self.n_simulations,
            "n_trades":         self.n_trades,
            "initial_equity":   self.initial_equity,
            "terminal_p05":     round(self.p05, 2),
            "terminal_p25":     round(self.p25, 2),
            "terminal_p50":     round(self.p50, 2),
            "terminal_p75":     round(self.p75, 2),
            "terminal_p95":     round(self.p95, 2),
            "mean_terminal":    round(self.mean_terminal, 2),
            "std_terminal":     round(self.std_terminal, 2),
            "prob_profit_pct":  round(self.prob_profit * 100, 2),
            "ruin_prob_pct":    round(self.ruin_probability * 100, 2),
            "median_max_dd_pct":round(self.median_max_dd, 2),
            "cvar_5pct":        round(self.cvar_5pct, 2),
        }


# ── Monte Carlo engine ────────────────────────────────────────────────────────

class MonteCarloSimulator:
    """
    Runs N simulations by resampling a historical trade P&L sequence.

    Usage:
        result = MonteCarloSimulator().run(
            trades          = report.trades,
            initial_equity  = 100_000,
            n_simulations   = 5_000,
        )
        print(result.summary())
    """

    def run(
        self,
        trades:           list[dict[str, Any]],
        initial_equity:   float,
        n_simulations:    int   = 5_000,
        ruin_threshold:   float = 0.50,   # equity < 50% of initial = ruin
        mode:             str   = "bootstrap",   # "bootstrap" | "block"
        block_size:       int   = 5,              # for block bootstrap
        seed:             int | None = None,
    ) -> MonteCarloResult:
        """
        Parameters
        ----------
        trades          : list of trade dicts from PerformanceReport
        initial_equity  : starting equity for each simulation path
        n_simulations   : number of Monte Carlo runs
        ruin_threshold  : equity fraction below which a run counts as ruin
        mode            : "bootstrap" (random draw) or "block" (block bootstrap)
        block_size      : block size for block bootstrap (default 5 trades)
        seed            : random seed for reproducibility (None = random)
        """
        if seed is not None:
            random.seed(seed)

        pnls = [float(t.get("realised_pnl", 0)) for t in trades]
        if not pnls:
            raise ValueError("No trades to simulate — run a backtest first.")

        n_trades = len(pnls)
        ruin_floor = initial_equity * ruin_threshold

        # Historical (original-order) equity curve
        original_curve = _build_curve(pnls, initial_equity)

        # Run simulations
        all_paths: list[SimPath] = []
        for _ in range(n_simulations):
            if mode == "block":
                sampled_pnls = _block_resample(pnls, n_trades, block_size)
            else:
                sampled_pnls = [random.choice(pnls) for _ in range(n_trades)]

            curve   = _build_curve(sampled_pnls, initial_equity)
            term_eq = curve[-1]
            max_dd  = _max_drawdown(curve)
            sharpe  = _sharpe(sampled_pnls, initial_equity)
            cagr    = _cagr(initial_equity, term_eq, n_trades)
            streak  = _worst_loss_streak(sampled_pnls)

            all_paths.append(SimPath(
                terminal_equity  = term_eq,
                max_drawdown_pct = max_dd,
                cagr_pct         = cagr,
                sharpe           = sharpe,
                worst_streak     = streak,
                equity_curve     = curve,
            ))

        return self._aggregate(all_paths, initial_equity, n_trades,
                               ruin_floor, original_curve)

    # ── Aggregation ───────────────────────────────────────────────────────────

    def _aggregate(
        self,
        paths:          list[SimPath],
        initial_equity: float,
        n_trades:       int,
        ruin_floor:     float,
        original_curve: list[float],
    ) -> MonteCarloResult:
        terminals = sorted(p.terminal_equity for p in paths)
        n = len(terminals)

        def pct(frac: float) -> float:
            idx = max(0, min(n - 1, int(frac * n)))
            return terminals[idx]

        mean_t = sum(terminals) / n
        std_t  = math.sqrt(sum((t - mean_t) ** 2 for t in terminals) / max(n - 1, 1))

        # CVaR 5%: mean of the worst 5% of terminal equities
        n_tail  = max(1, int(0.05 * n))
        cvar    = sum(terminals[:n_tail]) / n_tail

        ruin_count   = sum(1 for t in terminals if t < ruin_floor)
        profit_count = sum(1 for t in terminals if t > initial_equity)

        # Per-percentile equity curves (for fan chart)
        # Build by taking the Kth percentile equity at each step across all paths
        step_count = n_trades + 1
        curve_bands = {
            "p05": [], "p25": [], "p50": [], "p75": [], "p95": []
        }
        fracs = {"p05": 0.05, "p25": 0.25, "p50": 0.50, "p75": 0.75, "p95": 0.95}

        for step in range(step_count):
            equities_at_step = sorted(p.equity_curve[step] for p in paths)
            m = len(equities_at_step)
            for key, frac in fracs.items():
                idx = max(0, min(m - 1, int(frac * m)))
                curve_bands[key].append(equities_at_step[idx])

        result = MonteCarloResult(
            n_simulations   = n,
            n_trades        = n_trades,
            initial_equity  = initial_equity,
            paths           = paths,
            p05  = pct(0.05),  p10 = pct(0.10),
            p25  = pct(0.25),  p50 = pct(0.50),
            p75  = pct(0.75),  p90 = pct(0.90),
            p95  = pct(0.95),
            ruin_probability = ruin_count / n,
            prob_profit      = profit_count / n,
            median_max_dd    = sorted(p.max_drawdown_pct for p in paths)[n // 2],
            cvar_5pct        = cvar,
            mean_terminal    = mean_t,
            std_terminal     = std_t,
            curve_p05  = curve_bands["p05"],
            curve_p25  = curve_bands["p25"],
            curve_p50  = curve_bands["p50"],
            curve_p75  = curve_bands["p75"],
            curve_p95  = curve_bands["p95"],
            curve_original = original_curve,
        )
        return result


# ── Mathematical helpers ──────────────────────────────────────────────────────

def _build_curve(pnls: list[float], initial: float) -> list[float]:
    """Build an equity curve from a P&L sequence."""
    curve = [initial]
    eq = initial
    for pnl in pnls:
        eq = max(eq + pnl, 0.01)   # floor at $0.01 to avoid negative equity
        curve.append(eq)
    return curve


def _max_drawdown(curve: list[float]) -> float:
    """Peak-to-trough drawdown as a percentage."""
    peak = curve[0]
    max_dd = 0.0
    for v in curve[1:]:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return round(max_dd * 100, 3)


def _sharpe(pnls: list[float], initial_equity: float) -> float:
    """Simplified annualised Sharpe from trade returns."""
    if len(pnls) < 2:
        return 0.0
    returns = [p / initial_equity for p in pnls]
    mu  = sum(returns) / len(returns)
    std = math.sqrt(sum((r - mu) ** 2 for r in returns) / (len(returns) - 1))
    if std == 0:
        return 0.0
    return round(mu / std * math.sqrt(252), 3)


def _cagr(initial: float, terminal: float, n_trades: int) -> float:
    """Annualised return assuming ~252 trades per year."""
    if initial <= 0 or terminal <= 0 or n_trades <= 0:
        return 0.0
    years = n_trades / 252
    if years < 1e-6:
        return 0.0
    try:
        return round((terminal / initial) ** (1 / years) * 100 - 100, 2)
    except Exception:
        return 0.0


def _worst_loss_streak(pnls: list[float]) -> int:
    """Longest consecutive losing run."""
    max_s = cur_s = 0
    for p in pnls:
        if p < 0:
            cur_s += 1
            max_s = max(max_s, cur_s)
        else:
            cur_s = 0
    return max_s


def _block_resample(pnls: list[float], n: int, block_size: int) -> list[float]:
    """Block bootstrap: draw consecutive blocks with replacement."""
    result: list[float] = []
    while len(result) < n:
        start = random.randint(0, len(pnls) - 1)
        block = pnls[start:start + block_size]
        if not block:
            block = [pnls[start]]
        result.extend(block)
    return result[:n]
