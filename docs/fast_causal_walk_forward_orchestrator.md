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

For new `BOOTSTRAP_THEN_WF` experiments, the first autonomous boundary is `BOOTSTRAP_RESEARCH_REQUIRED`. Use the normal read-only research/query tools over the immutable bootstrap window, then call `record_walk_forward_review` with `review_type="BOOTSTRAP"` and the selected BASE rule events. That atomic write freezes the rules at `research_protocol.walk_forward_start` and changes phase to `RESEARCH_WF`. Candidate and teacher scanning before that cutoff is blocked.

Fixed-rule OOS validation remains a normal materialized Crypto Strategy Lab run from a verified walk-forward head; it is not a separate learning phase.

The autonomous action consumes routine deterministic scan checkpoints internally. It returns one of four useful classes:

- a genuine ChatGPT judgment packet:
  - `CANDIDATE_DECISION_REQUIRED`
  - `TEACHER_REVIEW_REQUIRED`
  - `TEACHER_LOSS_REVIEW_REQUIRED` only when a source teacher LOSS has an exact immutable paired opposite WIN
  - `LOSS_REVIEW_REQUIRED`
  - `PERIODIC_REVIEW_REQUIRED`

Verified teacher LOSS/LOSS and LOSS/BREAKEVEN pairs are deterministic non-actions: they remain in the immutable reference data/analytics but do not consume a ChatGPT teacher review. This optimization applies only to teacher learning; a prospective candidate admitted by an already-active ENTRY/FLIP still settles and reviews its loss normally.
- `AUTONOMOUS_CONTINUE`: the current MCP request reached its safe deterministic slice budget; immediately call `continue_walk_forward_autonomous` again with the returned sequence/hash;
- `NO_MORE_ACTION_IN_SCAN`: there is no further causal action in the available reference data;
- an inspection-required status: stop automatic progression and inspect the blocker instead of guessing.

Each autonomous result includes an `autonomous` object. When `continue_without_user=true`, ChatGPT should continue within the same response and should not emit a routine progress snapshot or wait for the user. Judgment packets also set `assistant_judgment_required=true`: ChatGPT must perform the same full reasoning as the interactive workflow, persist the judgment using the existing decision/review action with `autonomous_mode=true`, and then resume autonomous continuation. The autonomous judgment actions propagate `max_scan_slices` so a win, loss review, teacher review, or periodic review can immediately continue through routine scan checkpoints.

The low-level interactive workflow remains available:

1. `read_walk_forward_experiment`
2. `advance_walk_forward`
3. If the action returns `SCAN_CHECKPOINTED`, immediately call `advance_walk_forward` again with the returned sequence/hash.
4. Resolve judgment states with `submit_walk_forward_decision`, `record_walk_forward_review`, or `record_walk_forward_teacher_review`.

No autonomous action invents a LONG/SHORT view, teacher rule, loss veto, FLIP, or periodic-review decision. Those remain ChatGPT judgment.

## Monthly batch OOS mode

Fresh experiments may opt into:

```json
{
  "rule_update_policy": {
    "mode": "MONTHLY_BATCH_OOS",
    "interval_months": 1,
    "freeze_between_reviews": true
  }
}
```

The default remains `TRADE_BY_TRADE`.

In monthly batch mode the accelerated orchestrator consumes prospective
candidate execution, settlements, and teacher observations deterministically
until the one-month boundary. It does not request per-trade ChatGPT direction,
teacher-rule, or prospective-loss judgments. The current
`strategy_action` is durably frozen before outcome reveal, while the rule
snapshot remains unchanged for the entire month.

At `PERIODIC_REVIEW_REQUIRED` the response becomes the batch-learning
boundary. It includes the completed month's prospective trades, deferred
teacher contexts, rule-performance analytics, and a causal aggregate of all
source observations whose source outcome resolved during the month. An
opposite-side outcome contributes to that aggregate only if it had also
resolved by the boundary.

Any rule events recorded by that monthly review become effective at the
boundary and therefore apply only to the next frozen OOS month. Direct
per-trade ChatGPT-view calls and mid-month loss/teacher review writes are
rejected for this mode.

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

Large 15m paired Walk Forward source-candidate histories can exceed the secure-tunnel response lifetime if one MCP request scans the entire remaining reference run. The accelerated orchestrator therefore scans at most 4,096 candidate rows per request.

If that bounded slice contains no candidate or earlier teacher boundary, the orchestrator appends a `CHECKPOINT_CREATED` event with checkpoint type `CANDIDATE_SCAN_CURSOR_V1` and returns `SCAN_CHECKPOINTED`. The cursor stores the exact deterministic sort key:

```text
(entry_time, research_signal_index, side)
```

The next `advance_walk_forward` resumes strictly after that key, including correct handling of multiple opportunities at the same timestamp. No historical opportunity is skipped and no previously scanned row is repeatedly materialized.

A teacher, review, rule change, candidate/trade event, or other later causal mutation invalidates the old scan cursor automatically. The next scan then derives its start from the newer authoritative market-time state instead.

Teacher boundaries are also enforced before rule matching: once a pending teacher winner has resolved by the decision time of the next candidate row, scanning stops and returns `TEACHER_REVIEW_REQUIRED` even when the current strategy has no ENTRY rule that would admit that row. This avoids scanning hundreds of thousands of irrelevant rows before the first teacher review.

For canonical paired `WALK_FORWARD` references, teacher chronology comes from the immutable source rows in `research_sampling_trades`, not from the portfolio `trades` population. Source-row sampling intentionally allows overlap, so `WAIT_UNTIL_CLOSED` suppresses only additional RESEARCH-equity entries; it does not remove overlapping observations from teacher learning. If the fund cursor has already advanced beyond an unresolved teacher resolution, the teacher boundary is still surfaced before the next eligible candidate. Existing experiments do not retroactively backfill teacher observations behind an already-processed teacher cursor.

After a teacher boundary is hydrated, the orchestrator applies `causal_teacher_actionability_compression_v3`. The full fine-grained entry-time phase fingerprint remains in the audit trail, but ChatGPT review is driven by **causal actionability novelty** rather than every DI/ADX/MACD/S/R/Ichimoku bucket change. Active-rule failures, unmatched or policy-blocked winners, verified source-loss/opposite-win FLIP opportunities, the first independent confirmation of each exact learned/refined rule version, genuine setup-family changes, and executable rule-set/version changes still surface. Repeated rule-covered winners with the same actionability signature, repeated unruled LOSS/LOSS observations, and ordinary structural variation auto-compress. A five-review per-episode guardrail compresses residual ordinary novelty while the high-priority exceptions above always break through. Deterministically compressed observations append an audited `TEACHER_RESOLVED/AUTO_COMPRESSED` event and scanning continues without an MCP/ChatGPT review round-trip. Teacher packets expose only causal episode progress (`research_episode_entries_seen_so_far`), never the eventual episode size. The immutable source row is never removed, so later rule analytics continue to use the full evidence population.

## Outcome firewall

`submit_walk_forward_decision` freezes ChatGPT's research view before the strategy outcome is opened.

The order is strict:

```text
ENTRY/VETO/FLIP evaluation -> strategy_action
CANDIDATE_CONTEXT_CAPTURED
  -> DECISION_FROZEN(strategy_action, chatgpt_view, confidence, reasoning)
  -> open exact paired outcome row for strategy_action
  -> OUTCOME_REVEALED
```

The outcome artifact is not opened until the frozen view event is durable. A retry after a transport/process interruption reuses the already-frozen evidence and cannot replace it.

ChatGPT disagreement never changes execution. If `strategy_action=LONG` and `chatgpt_view=SHORT`, the resolver reads the exact LONG row from the candidate's immutable pair.

If an active causal FLIP changes the executable side, the resolver selects the opposite row with the same `walk_forward_candidate_id`. Both sides were independently simulated when the reference run was created, so TP3 and other asymmetric outcomes are never inferred or mirrored.

## Deterministic settlement

`resolve_walk_forward_trade` uses:

```text
risk_amount = current_research_equity * risk_pct / 100
net_pnl     = risk_amount * immutable_pair_net_r
equity_after = equity_before + net_pnl
```

Research-sample absolute P&L is not reused because paired Walk Forward observations run on independent fixed research equity. Net R is the portable outcome used to compound the causal walk-forward ledger.

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

When the next reference winner resolves before a prospective candidate, `advance_walk_forward` returns `TEACHER_REVIEW_REQUIRED` instead of scanning past it. The packet includes the teacher boundary, active rule versions/counts, and when the exact paired source context is available, entry-time context plus current-rule coverage.

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
