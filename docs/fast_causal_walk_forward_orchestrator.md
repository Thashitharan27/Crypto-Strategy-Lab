# Fast causal walk-forward orchestrator

The fast workflow reduces MCP/chat round-trips without weakening causal research rules.

## Principle

Crypto Strategy Lab performs deterministic work. ChatGPT/human judgment is still required for:

- candidate LONG/SHORT choice and confidence;
- teacher ENTRY learning/refinement;
- prospective loss review and any VETO/ENTRY/FLIP change;
- periodic review decisions.

The event stream remains authoritative and every mutation remains sequence/hash guarded and idempotent.

## Preferred workflow

1. `read_walk_forward_experiment`
2. `advance_walk_forward`
3. If the action returns `SCAN_CHECKPOINTED`, immediately call `advance_walk_forward` again with the returned sequence/hash. This is deterministic continuation, not a judgment point.
4. Stop only when the action returns one of the judgment states:
   - `CANDIDATE_DECISION_REQUIRED`
   - `TEACHER_REVIEW_REQUIRED`
   - `LOSS_REVIEW_REQUIRED`
   - `PERIODIC_REVIEW_REQUIRED`
5. For a candidate, call `submit_walk_forward_decision` with the returned candidate ID/token, LONG/SHORT, confidence, and reasoning.
6. For a loss/periodic review, call `record_walk_forward_review`, optionally with causal rule events.
7. For a teacher winner, call `record_walk_forward_teacher_review`, optionally with `ENTRY_LEARNED` / `ENTRY_REFINED` rule events.

When `auto_advance=true`, deterministic work continues automatically after a completed judgment until the next judgment boundary or a bounded scan checkpoint.

## Bounded scan checkpoints

Large 15m Every Viable Entry histories can exceed the secure-tunnel response lifetime if one MCP request scans the entire remaining reference run. The accelerated orchestrator therefore scans at most 4,096 candidate rows per request.

If that bounded slice contains no candidate or earlier teacher boundary, the orchestrator appends a `CHECKPOINT_CREATED` event with checkpoint type `CANDIDATE_SCAN_CURSOR_V1` and returns `SCAN_CHECKPOINTED`. The cursor stores the exact deterministic sort key:

```text
(entry_time, research_signal_index, side)
```

The next `advance_walk_forward` resumes strictly after that key, including correct handling of multiple opportunities at the same timestamp. No historical opportunity is skipped and no previously scanned row is repeatedly materialized.

A teacher, review, rule change, candidate/trade event, or other later causal mutation invalidates the old scan cursor automatically. The next scan then derives its start from the newer authoritative market-time state instead.

Teacher boundaries are also enforced before rule matching: once a pending teacher winner has resolved by the decision time of the next candidate row, scanning stops and returns `TEACHER_REVIEW_REQUIRED` even when the current strategy has no ENTRY rule that would admit that row. This avoids scanning hundreds of thousands of irrelevant rows before the first teacher review.

## Outcome firewall

`submit_walk_forward_decision` uses the lower-level `freeze_and_reveal_walk_forward_candidate` path.

The order is strict:

```text
CANDIDATE_CONTEXT_CAPTURED
  -> DECISION_FROZEN (append + flush + fsync)
  -> open outcome-bearing EVE artifact
  -> OUTCOME_REVEALED
```

The outcome artifact is not opened by the reveal path until the frozen decision event is durable. A retry after a transport/process interruption reuses the already-frozen decision and cannot replace it.

If ChatGPT chooses the opposite side from the source candidate, the tool requires an exact immutable Every Viable Entry observation for that signal and frozen side. If there is no unique exact observation, the decision stays frozen and no outcome is revealed. The tool never estimates or mirrors the source-side result.

## Deterministic settlement

`resolve_walk_forward_trade` uses:

```text
risk_amount = current_research_equity * risk_pct / 100
net_pnl     = risk_amount * immutable_pair_net_r
equity_after = equity_before + net_pnl
```

Research-sample absolute P&L is not reused because Every Viable Entry observations run on independent fixed research equity. Net R is the portable outcome used to compound the causal walk-forward ledger.

Teacher trades never call settlement and therefore never change walk-forward equity.

## Loss review packet

After a deterministic research loss, the orchestrator returns `LOSS_REVIEW_REQUIRED` with:

- frozen side, confidence, and reasoning;
- admitting ENTRY group(s), VETO/FLIP matches;
- entry-time context;
- revealed immutable outcome and ledger settlement;
- prior-only causal statistics for all research trades, same profile, same frozen side, and the matched ENTRY groups.

A loss remains in equity. `record_walk_forward_review` can record `KEEP_LOSS` with no rule change or append justified prospective rule events. Rules apply only after the review event.

## Teacher review packet

When the next reference winner resolves before a prospective candidate, `advance_walk_forward` returns `TEACHER_REVIEW_REQUIRED` instead of scanning past it. The packet includes the teacher boundary, active rule versions/counts, and when the exact EVE context is available, entry-time context plus current-rule coverage.

`record_walk_forward_teacher_review` records the teacher event and can append ENTRY learning/refinement in the same guarded operation chain. Teacher evidence is learning-only and does not affect equity.

## Periodic review

If the event stream already contains a prior periodic/quarterly `REVIEW_COMPLETED` event, `advance_walk_forward` checks the configured interval (default 3 months) and stops at `PERIODIC_REVIEW_REQUIRED` when the market cursor reaches the next review boundary.

Migrated experiments with no prior periodic review anchor are not forced into a guessed boundary.

## Low-level recovery actions

The high-level path is preferred, but these remain available for inspection/recovery:

- `get_next_walk_forward_candidate`
- `freeze_and_reveal_walk_forward_candidate`
- `resolve_walk_forward_trade`
- `append_walk_forward_experiment_event`

This keeps the protocol debuggable without requiring normal research to manually assemble every event.