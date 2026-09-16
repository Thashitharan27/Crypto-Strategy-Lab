# Causal Walk-Forward State MCP

The unified Crypto Strategy Lab MCP on port `8766` includes a restricted persistence surface for causal walk-forward research.

This is intentionally **not** a general file-writing API. State is confined to:

```text
<project root>/walk_forward_state/
```

A `state_id` may contain only letters, numbers, `_`, and `-`. The service derives exactly two files:

```text
<state_id>_state.md
<state_id>_events.jsonl
```

For example:

```text
state_id = BTCUSDT_1D_WF_84f8369

walk_forward_state/BTCUSDT_1D_WF_84f8369_state.md
walk_forward_state/BTCUSDT_1D_WF_84f8369_events.jsonl
```

The runtime directory is ignored by Git so evolving walk-forward state is not accidentally committed as source code.

## Tools

### `create_walk_forward_state`

Creates the canonical Markdown snapshot and the JSONL audit log. Creation fails if either derived file already exists; it never overwrites an existing walk-forward state.

Arguments:

```text
state_id
markdown
initial_event (optional JSON object)
```

The result returns the Markdown SHA-256 digest. Preserve that digest for the next update.

### `read_walk_forward_state`

Reads the complete canonical Markdown snapshot plus a bounded tail of audit records.

Arguments:

```text
state_id
recent_events = 50   # 0..200
```

The response includes the current `sha256`.

### `update_walk_forward_state`

Atomically replaces only the canonical Markdown snapshot. The caller must provide the SHA-256 digest returned by the latest read/create/update.

Arguments:

```text
state_id
markdown
expected_sha256
event (optional JSON object describing the causal change)
```

If another process/chat has already changed the state, the hash comparison fails and the caller must read the current state again before attempting an update. This prevents stale chats from silently overwriting newer causal state.

Every successful update automatically appends a JSONL audit record containing the before/after hashes. Supplying an `event` object is strongly recommended for causal changes such as:

```json
{
  "type": "RULE_REFINED",
  "rule": "Entry #17",
  "effective_from": "2021-05-06",
  "reason": "Resolved walk-forward evidence"
}
```

### `append_walk_forward_event`

Appends an audit event without altering the canonical Markdown snapshot. The event is linked to the SHA-256 of the current state at append time.

Useful event types include:

```text
FROZEN_DECISION
TRADE_RESOLVED
TEACHER_WIN_RESOLVED
ENTRY_RULE_LEARNED
VETO_RULE_LEARNED
RULE_REFINED
THREE_MONTH_REVIEW
CURSOR_ADVANCED
```

## Safety properties

The walk-forward state subsystem has the following boundaries:

- no arbitrary file path parameter;
- no directory traversal;
- no absolute paths;
- no symlinked state/event targets;
- Markdown capped at 2 MiB per state;
- individual event payloads capped at 64 KiB;
- reads return at most 200 recent audit events;
- Markdown updates use a same-directory temporary file, `fsync`, and `os.replace`;
- JSONL history is append-only through the MCP API;
- updates require optimistic SHA-256 concurrency control;
- no shell, source-editing, credentials, exchange-order, or live-trading capability is added.

## Recommended causal structure

A canonical state file can use this layout:

```markdown
# BTCUSDT 1D Causal Walk-Forward State

## Immutable Reference
BTCUSDT_1d_84f83690203a4b429b8999cc6608db23

## Core Execution
- Strategy TF: 1D
- Intrabar: 1m
- Entry mode: WAIT_UNTIL_CLOSED
- Risk: 1% per trade
- SL: 1 ATR
- TP: 1R
- S/R: ON
- Market regime: ASSET_RETURN
- Max active positions: 1

## Causal Rules
- Teacher trades = training evidence only
- Teacher P&L never affects WF equity
- Only already-learned ENTRY groups may trade
- Bear profiles disabled until first causal Bear winner teaches ENTRY
- Rules apply prospectively only
- Decisions frozen before outcome lookup
- Actual WF losses remain booked

## Current State
- Current date cursor: 2021-05-05
- Canonical equity: $1,044.47
- Open WF position: NONE
- Last completed WF trade: 2021-05-01 Bull Short
- Last outcome: WIN
- Rules learned: Entry #1–#31
- Next action: evaluate May 5, 2021

## Entry Rules
### Entry #1
...

## Veto Rules
...

## Rule Refinements
...

## Walk-Forward Ledger
| # | Entry Date | Profile | Side | Rule | Frozen AI Read | Result | R | Equity After |
|---|---|---|---|---|---|---|---|---|

## Teacher Learning Ledger
| Teacher Resolution | Profile | Result | Action |
|---|---|---|---|

## 3-Month Reviews
...
```

The Markdown is the current human/AI-readable canonical snapshot. Historical evolution belongs in the JSONL audit log. A refinement should therefore update the canonical rule text while recording an event with its effective-from date; earlier history is not rewritten.

## Suggested workflow when continuing in a new chat

1. Call `read_walk_forward_state(state_id)`.
2. Verify the immutable reference, cursor, canonical equity, open position, and active rules.
3. Continue the causal walk-forward using only information available at each prospective entry.
4. Append frozen decisions and resolved outcomes as audit events.
5. When the canonical state changes, call `update_walk_forward_state` using the hash from the latest read/update and include a descriptive event.
6. If the update reports a stale hash, read again and reconcile rather than overwriting.
