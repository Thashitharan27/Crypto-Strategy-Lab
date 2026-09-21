# Deterministic walk-forward candidate engine

`get_next_walk_forward_candidate` moves historical candidate filtering out of ChatGPT and into Crypto Strategy Lab.

## Source of candidates

The immutable reference run must contain research sampling in `WALK_FORWARD` mode. Each viable source opportunity has an immutable LONG/SHORT pair, and the scanner consumes only rows with `walk_forward_candidate_source=true`. The scanner uses:

- `artifacts/research_sampling_trades.parquet` as the historical opportunity stream;
- `artifacts/feature_context.parquet` as the exact causal feature snapshot;
- the exact join `research_signal_index = strategy_index`;
- the verified causal experiment event stream as the rule/chronology source of truth.

Hydrated candidate/teacher context now also exposes a compact
`ichimoku_trade_context_v1` block for strategy-TF and available 1h/4h/1D
Ichimoku evidence. It is deliberately optional: immutable reference runs created
before Ichimoku research remain valid and return
`available=false, availability_reason=NOT_PRESENT_IN_REFERENCE_RUN` rather than
raising or reconstructing later data. Review methodology requires ChatGPT to
inspect this block when available alongside S/R, DI/ADX, EMA/MR,
MACD/momentum, and flow.

It does **not** start a new backtest to find each candidate and does not rewrite the reference run.

## Tool contract

```text
get_next_walk_forward_candidate(
    experiment_id,
    operation_id,
    expected_sequence,
    expected_state_hash,
    max_scan_rows=250000,
)
```

The call is pinned to a previously read sequence and state hash. Stale callers fail closed.

## Deterministic rule evaluation

At the verified chain head the scanner materializes the currently active strategy and applies the same Strategy Builder semantics:

- conditions inside one group are `ALL` / AND;
- ENTRY groups are alternative theses / OR;
- a candidate needs at least one complete ENTRY group match;
- any complete VETO group blocks the candidate;
- any complete FLIP group changes the deterministic rule-effective side;
- missing ENTRY evidence cannot make an ENTRY pass;
- missing optional evidence cannot manufacture a VETO or FLIP.

Profiles without an active causal ENTRY group are disabled by the materialized strategy and cannot create candidates.

## Outcome firewall

Each paired Walk Forward row contains entry context and resolved outcome columns. The scanner never returns an arbitrary outcome row, and counterfactual rows are never candidate sources.

The captured payload contains only:

- candidate/reference identity;
- entry/decision timestamps;
- matched rule groups and exact strategy snapshot hash;
- a whitelist of engine-computed entry values;
- the complete `feature_context` row, whose PreparedBacktestFrame contract verifies causal availability at the decision candle.

Exit time, P&L, R result, fees, holding period and other resolved-outcome fields are not returned in the candidate context.

A SHA-256 `feature_hash` and `candidate_token` bind the frozen context to the exact experiment head and strategy snapshot.

## Stateful capture

When the first eligible opportunity is found the tool immediately appends:

```text
CANDIDATE_CONTEXT_CAPTURED
```

and returns the new sequence/state hash. The next required causal event is `DECISION_FROZEN`.

The scanner refuses to advance while a candidate is still captured/frozen/revealed but not complete or invalidated. Reusing the same `operation_id` returns the already-captured candidate rather than scanning forward again.

## Teacher chronology guard

Teacher/reference winners can change future ENTRY rules only after they resolve. For paired `WALK_FORWARD` references, the unresolved teacher stream is drawn from overlap-independent source rows rather than portfolio trades, so `WAIT_UNTIL_CLOSED` cannot suppress teacher eligibility. The scanner therefore compares the next unresolved teacher resolution boundary with the next eligible candidate's decision time.

If the teacher resolves first, the tool returns:

```text
status = TEACHER_DUE_FIRST
```

and does not capture the later candidate. ChatGPT must process the teacher event first, persist any learning/no-change decision, read the new chain head, and call the scanner again.

This prevents a later candidate from being evaluated with a rule state that should have changed at an earlier teacher resolution.

## Typical loop

```text
read_walk_forward_experiment
        ↓
get_next_walk_forward_candidate
        ↓
TEACHER_DUE_FIRST? ── yes ─→ process/persist teacher → read head → scan again
        │
        no
        ↓
CANDIDATE_CONTEXT_CAPTURED
        ↓
ChatGPT chooses LONG/SHORT + confidence using context only
        ↓
append DECISION_FROZEN at returned state hash
        ↓
reveal/resolve through the existing causal workflow
        ↓
review loss if applicable; learn prospectively only
        ↓
read new head → scan again
```

The candidate engine does not place orders, start backtests, reveal outcomes, or promote research rules to shadow/live.
