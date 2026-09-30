# Single-strategy edge lifecycle

## Purpose

The edge lifecycle layer answers one question for one causal walk-forward experiment at a time:

> If this strategy's recent edge deteriorates, can capital be switched off while the same strategy continues to be observed in shadow, and can capital be restored only after causal recovery evidence appears?

It is deliberately not a multi-strategy allocator. Run it independently for EMA, FVG, DI Direction, Mean Reversion, or any other strategy, then compare their summaries later.

## Design

The authoritative walk-forward experiment is unchanged. Candidate generation, ENTRY/VETO/FLIP learning, outcome revelation, and the RESEARCH ledger continue exactly as before.

The lifecycle tool performs a read-only causal replay over resolved RESEARCH trades:

```text
strategy trade stream
       |
       +--> continuous strategy result
       |
       +--> capital gate
              |
              +--> LIVE   : trade contributes to managed equity
              |
              +--> SHADOW : trade is observed but contributes no managed equity
```

A state change is effective only after the trade that supplied the evidence resolves. A LIVE loss that confirms decay is still a LIVE loss. A SHADOW win that confirms recovery is still a SHADOW observation. The next trade sees the new state.

## Immutable policy

No edge thresholds are invented from completed outcomes. To enable the replay, freeze `edge_lifecycle_policy` in the experiment definition before evaluating the OOS chronology.

Example shape:

```json
{
  "edge_lifecycle_policy": {
    "enabled": true,
    "initial_state": "LIVE",
    "live_lookback_trades": 20,
    "live_min_trades": 20,
    "suspend_expectancy_r": 0.0,
    "suspend_net_r": -3.0,
    "shadow_lookback_trades": 10,
    "shadow_min_trades": 10,
    "recover_expectancy_r": 0.15,
    "recover_net_r": 1.5
  }
}
```

The numbers above illustrate the schema only; they are not recommended defaults. Enabled policies must supply their own thresholds. Recovery thresholds must be stronger than suspension thresholds so the gate has hysteresis instead of oscillating on noise.

## Transition rules

While LIVE, only LIVE observations since the most recent transition are considered. After `live_min_trades`, the most recent `live_lookback_trades` trigger SHADOW when both:

```text
recent expectancy <= suspend_expectancy_r
AND
recent net R      <= suspend_net_r
```

While SHADOW, all strategy trades continue to be observed. After `shadow_min_trades`, the most recent `shadow_lookback_trades` trigger LIVE when both:

```text
shadow expectancy >= recover_expectancy_r
AND
shadow net R      >= recover_net_r
```

No rule learning or strategy parameters are changed by these transitions.

## Output

`summarize_walk_forward_edge_lifecycle(experiment_id)` reports:

- the current capital state;
- every LIVE -> SHADOW and SHADOW -> LIVE transition with its causal evidence;
- every resolved trade annotated with the capital state that applied to it;
- the always-on strategy result;
- the edge-managed LIVE result;
- the SHADOW-only result;
- losses avoided while shadowed;
- profits missed while shadowed;
- managed versus continuous final equity using the experiment risk model.

The summary is intentionally per strategy. A future portfolio summary can combine completed strategy summaries without changing their causal histories.
