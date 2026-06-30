# FX Strategy Validation Evidence

This directory stores the safe, public evidence trail for the shadow FX strategy tests used by the Hermes infrastructure project.

## Safety scope

- **Read-only research only.** These scripts fetch candles and run local backtests; they do not place orders.
- **No credentials committed.** OANDA/API credentials stay server-side in the live bot environment and are not copied here.
- **Research-only gate.** A strategy is not considered deployable unless it passes the decision gate in the validation JSON.

## Current candidate under test

The best pocket found so far is:

| Field | Value |
|---|---|
| Instrument | `USD_JPY` |
| Signal | M15 Donchian breakout |
| Action tested | Inverted / faded signal |
| Trend context | H1 EMA trend filter |
| ADX min | `18` |
| Stop / target | `1.0 ATR / 2.0 ATR` |
| Session | `07:00–17:00 UTC`, excluding `10:00` and `11:00` |
| Max spread | `1.6 pips` |

## Directory layout

```text
research/fx-strategy-validation/
├── README.md
├── archive/
│   ├── scripts/   # exact research scripts used during discovery
│   └── results/   # original summary/trade outputs from discovery runs
└── results/       # stronger validation outputs from scripts/fx_winning_strategy_validation.py
```

## Re-run validation

From the repo root on the live VPS:

```bash
python3 scripts/fx_winning_strategy_validation.py --count 30000
```

Use `--use-cache` only when intentionally reproducing against cached candles. The default forces the optimizer path to fetch fresh candles through its OANDA data adapter.

## Anti-fake-output checks

Each validation JSON records:

- raw candle row count and time range
- SHA-256 hash of the canonical raw candle dataframe
- SHA-256 hash of the optimizer source file
- SHA-256 hash of the generated trades
- deterministic rerun hash comparison on the same in-memory dataset
- fold-by-fold performance summary
- bootstrap expectancy confidence interval
- explicit pass/fail decision gate

## Latest validation run

Fresh validation was run from the repo root with:

```bash
/usr/local/lib/trading-venv/bin/python scripts/fx_winning_strategy_validation.py --count 30000
```

Output files:

- [`results/usd_jpy_m15_donchian_fade_validation_20260630T120042Z.json`](results/usd_jpy_m15_donchian_fade_validation_20260630T120042Z.json)
- [`results/usd_jpy_m15_donchian_fade_trades_20260630T120042Z.csv`](results/usd_jpy_m15_donchian_fade_trades_20260630T120042Z.csv)

Summary:

| Metric | Overall | OOS 30% |
|---|---:|---:|
| Trades | `34` | `22` |
| Win rate | `35.29%` | `40.91%` |
| Profit factor | `1.09` | `1.323` |
| Net R | `+1.86R` | `+4.017R` |
| Expectancy | `+0.0547R` | `+0.1826R` |
| Max drawdown | `7.448R` | `7.448R` |

Anti-fake-output checks passed:

- raw data validation: passed
- raw candle SHA-256 captured
- optimizer SHA-256 captured
- trade CSV row count: `34`
- deterministic rerun trade hash matched

Decision gate result: **FAIL / RESEARCH ONLY**.

Reason: profitability improved, but there are only `34` trades, only `40%` of folds are positive, and the bootstrap 95% expectancy interval still crosses zero.

## Current interpretation

This is a **profitability research candidate**, not a live deployment candidate. If the decision gate fails, the correct conclusion is: keep testing, do not promote.
