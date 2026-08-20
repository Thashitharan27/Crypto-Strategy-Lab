# State Transition Research

`crypto_strategy_lab.state_transition_research` adds a research-only Markov/state-transition layer to Crypto Strategy Lab.

## Scope

This first stage deliberately does **not** alter entries, stops, targets, sizing, or Strategy Profile selection.

It answers two questions:

1. Given the current broad market state, what state historically came next?
2. How did actual backtest trades perform when grouped by **DI bucket × DI movement × volatility state**?

## Broad market state

The default state model mirrors the simple three-state approach:

- `BULL`: trailing 20-day close return >= +5%
- `SIDEWAYS`: trailing 20-day close return between -5% and +5%
- `BEAR`: trailing 20-day close return <= -5%

The output is a transition matrix with both probability and sample count. Rows whose current-state sample count is below the configured minimum are marked rather than silently trusted.

## Volatility state

Daily volatility is the rolling standard deviation of one-day returns. The state is:

- `LOW`
- `NORMAL`
- `ELEVATED`

The low/high boundaries are rolling historical quantiles. They are shifted by one day before classification, so the current day's boundary never uses future observations.

## DI state

Trade rows use `directional_di` when available. Fallbacks are `max(plus_di, minus_di)` and finally `di_spread`.

Default buckets:

- 0-5
- 5-10
- 10-15
- 15-20
- 20-25
- 25-30
- 30+

DI movement uses `directional_di_change` when available, with fallbacks to existing DI-change telemetry. The default classification is:

- `RISING`: change > +0.5
- `STABLE`: change between -0.5 and +0.5
- `FALLING`: change < -0.5

## Generated files

Calling `generate_state_transition_reports(strategy_data, trades, run_dir)` creates:

`state_transition_research/daily_states.csv`

Daily close, trailing return, broad regime, rolling volatility, and volatility state.

`state_transition_research/regime_transition_matrix.csv`

Broad BULL/SIDEWAYS/BEAR transition probabilities and counts.

`state_transition_research/volatility_transition_matrix.csv`

LOW/NORMAL/ELEVATED volatility transition probabilities and counts.

`state_transition_research/current_regime_probabilities.csv`

Only the broad transition probabilities applicable to the most recent regime state.

`state_transition_research/di_state_volatility_trade_performance.csv`

Trade count, wins, win rate, net R, average R, and minimum-sample flag for every observed DI bucket × DI movement × volatility state combination.

## Example integration

```python
from crypto_strategy_lab.state_transition_research import generate_state_transition_reports

generate_state_transition_reports(data, trades, run_dir)
```

`data` is the strategy candle DataFrame used by the backtest; `trades` is the completed trade DataFrame.

## Research rules

Do not use the raw in-sample transition probabilities as a live entry filter. The next stage should evaluate them through walk-forward windows and verify that any proposed probability threshold improves out-of-sample expectancy with sufficient sample size.

A future Stage 2 can add the GUI controls and automatic worker export after the research report contract is validated.
