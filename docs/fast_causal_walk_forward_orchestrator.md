# Fast causal walk-forward orchestrator

The fast workflow reduces MCP/chat round-trips without weakening causal research rules.

## Principle

Crypto Strategy Lab performs deterministic work. ChatGPT/human judgment is still required for:

- an independent candidate LONG/SHORT view and confidence;
- teacher ENTRY learning/refinement;
- prospective loss review and any VETO/ENTRY/FLIP change;
- periodic review decisions.

The event stream remains authoritative and every mutation remains sequence/hash guarded and idempotent.

## Strategy action vs ChatGPT view

Candidate direction has two separate meanings and they must never be conflated:

- `strategy_action` is the executable side produced by the currently learned ENTRY/VETO/FLIP rules. This is the side whose immutable TP/SL outcome is revealed and the side used for walk-forward equity settlement.
- `chatgpt_view` is ChatGPT's independent LONG/SHORT research judgment, frozen before outcome together with confidence and reasoning. It never changes execution by itself.

A real causal FLIP rule changes `strategy_action`. ChatGPT disagreement does not.

Example:

```text
ENTRY admits LONG
no FLIP matches
strategy_action = LONG
chatgpt_view = SHORT (64%)
=> reveal and settle the LONG TP/SL outcome
```

If an active FLIP matches:

```text
ENTRY admits LONG
FLIP matches
strategy_action = SHORT
chatgpt_view = LONG (61%)
=> reveal and settle the SHORT TP/SL outcome
```

The MCP tool schema currently retains `final_action` as a compatibility wire argument. For `submit_walk_forward_decision` and `freeze_and_reveal_walk_forward_candidate`, that argument is interpreted as `chatgpt_view`; it does not override `strategy_action`. New `DECISION_FROZEN` events store both fields explicitly, with `final_action` retained only as a legacy executable alias equal to `strategy_action`.

## Preferred workflow

For normal long-running research, prefer `continue_walk_forward_autonomous` after verifying the authoritative experiment head.

The autonomous action consumes routine deterministic scan checkpoints internally. It returns one of four useful classes:

- a genuine ChatGPT judgment packet:
  - `CANDIDATE_DECISION_REQUIRED`
  - `TEACHER_REVIEW_REQUIRED`
  - `TEACHER_LOSS_REVIEW_REQUIRED`
  - `LOSS_REVIEW_REQUIRED`
  - `PERIODIC_REVIEW_REQUIRED`
- `AUTONOMOUS_CONTINUE`: the current MCP request reached its safe deterministic slice budget; immediately call `continue_walk_forward_autonomous` again with the returned sequence/hash;
- `NO_MORE_ACTION_IN_SCAN`: there is no further causal action in the available reference data;
- an inspection-required status: stop automatic progression and inspect the blocker instead of guessing.

Each autonomous result includes an `autonomous` object. When `continue_without_user=true`, ChatGPT should continue within the same response and should not emit a routine progress snapshot or wait for the user. Judgment packets also set `assistant_judgment_required=true`: ChatGPT must perform the same full reasoning as the interactive workflow, persist the judgment using the existing decision/review action, and then resume autonomous continuation.

The low-level interactive workflow remains available:

1. `read_walk_forward_experiment`
2. `advance_walk_forward`
3. If the action returns `SCAN_CHECKPOINTED`, immediately call `advance_walk_forward` again with the returned sequence/hash.
4. Resolve judgment states with `submit_walk_forward_decision`, `record_walk_forward_review`, or `record_walk_forward_teacher_review`.

No autonomous action invents a LONG/SHORT view, teacher rule, loss veto, FLIP, or periodic-review decision. Those remain ChatGPT judgment.

## Autonomous research and context safety

Autonomous mode is designed to maximize useful work per ChatGPT turn without making the conversation transcript the source of truth.

The authoritative state remains the experiment manifest plus append-only event stream. Every decision, review, rule mutation, settlement, and deterministic scan cursor is persisted before progression continues. A later ChatGPT turn can therefore re-read the experiment head and resume from the exact sequence/hash without relying on old conversational memory.

Context-safety rules for ChatGPT/Work:

- do not repeat `SCAN_CHECKPOINTED` or `AUTONOMOUS_CONTINUE` as user-facing snapshots;
- while `autonomous.continue_without_user=true`, keep working in the same response;
- use the complete causal packet for every judgment; never shorten the evidence packet merely to increase throughput;
- periodically prefer a clean turn boundary well before conversational context pressure becomes material;
- before a context-budget stop, finish the current judgment, persist it, and leave the experiment at a verified sequence/hash;
- label that clean stop `SAFE_STOP_CONTEXT_BUDGET` in the user summary; this is not an experiment event and does not change causal state;
- the next turn begins with `read_walk_forward_experiment` and resumes from the authoritative head.

A conservative operating target is a few dozen full judgment packets per ChatGPT response, not hundreds. Packet size varies substantially, so ChatGPT should stop earlier when loss, teacher, or periodic-review packets are unusually large. This protects reasoning quality while still eliminating routine user `continue` prompts.

The server also caps one autonomous MCP request to a small number of 4,096-row scan slices. Reaching that server-side request budget returns `AUTONOMOUS_CONTINUE`; it is a transport/runtime safeguard, not a reason to involve the user.

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

`submit_walk_forward_decision` freezes ChatGPT's research view before the strategy outcome is opened.

The order is strict:

```text
ENTRY/VETO/FLIP evaluation -> strategy_action
CANDIDATE_CONTEXT_CAPTURED
  -> DECISION_FROZEN(strategy_action, chatgpt_view, confidence, reasoning)
  -> open outcome-bearing EVE artifact for strategy_action
  -> OUTCOME_REVEALED
```

The outcome artifact is not opened until the frozen view event is durable. A retry after a transport/process interruption reuses the already-frozen evidence and cannot replace it.

ChatGPT disagreement never requires opposite-side EVE data for normal progression. If `strategy_action=LONG` and `chatgpt_view=SHORT`, the resolver reads the exact LONG sample. A missing SHORT sample therefore cannot block a valid LONG walk-forward trade.

Opposite-side EVE data is required only when the executable `strategy_action` itself is opposite the source sample, for example because an active causal FLIP rule changed LONG to SHORT. The tool never infers or mirrors an opposite TP3 result.

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

- executable `strategy_action`;
- frozen `chatgpt_view`, confidence, reasoning, and agreement/disagreement flag;
- admitting ENTRY group(s), VETO/FLIP matches;
- entry-time context;
- revealed immutable strategy outcome and ledger settlement;
- prior-only causal statistics for research trades admitted by the same strategy side/groups.

A loss remains in equity. `record_walk_forward_review` can record `KEEP_LOSS` with no rule change or append justified prospective rule events. Rules apply only after the review event.

Because ChatGPT's view is separately frozen before outcome, later analysis can measure agreement/disagreement performance, confidence buckets, and recurring disagreement reasons without contaminating the strategy ledger.

## Teacher review packet

When the next reference winner resolves before a prospective candidate, `advance_walk_forward` returns `TEACHER_REVIEW_REQUIRED` instead of scanning past it. The packet includes the teacher boundary, active rule versions/counts, and when the exact EVE context is available, entry-time context plus current-rule coverage.

`record_walk_forward_teacher_review` records the teacher event and can append ENTRY learning/refinement in the same guarded operation chain. Teacher evidence is learning-only and does not affect equity.

## Periodic review

New experiments store an immutable `periodic_review_policy.initial_anchor` policy. The default is `REFERENCE_PERIOD_START`, so before the first review exists, `advance_walk_forward` derives the anchor from the immutable reference period start and stops at `PERIODIC_REVIEW_REQUIRED` once the market cursor reaches the configured interval (default 3 months).

After a periodic/quarterly `REVIEW_COMPLETED` event exists, that review time becomes the anchor for the next interval.

`MANUAL` initial-anchor policy disables automatic scheduling of the first review. Migrated experiments with no prior periodic review remain protected from an invented historical boundary even if a new default policy is present.

## Low-level recovery actions

The high-level path is preferred, but these remain available for inspection/recovery:

- `get_next_walk_forward_candidate`
- `freeze_and_reveal_walk_forward_candidate`
- `resolve_walk_forward_trade`
- `append_walk_forward_experiment_event`

This keeps the protocol debuggable without requiring normal research to manually assemble every event.
