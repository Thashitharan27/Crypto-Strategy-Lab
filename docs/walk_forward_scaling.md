# Scalable causal walk-forward event storage

Long causal walk-forward experiments keep the append-only `events.jsonl` stream as
the authoritative research history, but routine execution no longer reparses and
rehashes that entire file for every event.

## Rebuildable sidecars

Each experiment may contain:

- `head.json` — compact current sequence/hash plus the authoritative event-file
  size and modification timestamp.
- `checkpoint.json` — derived causal state at a recent checkpoint. Reviews force
  a checkpoint; long runs also checkpoint periodically.
- `event_index.sqlite3` — rebuildable event projection used by hot-path reads,
  idempotency lookups, candidate state, rule lifecycle queries, and recent-event
  access.

These files are caches only. They can be deleted and rebuilt from
`manifest.json + events.jsonl`.

## Integrity model

`CausalExperimentStore.read()` remains the full audit path: it reads every
authoritative event and verifies sequence, previous hash, and resulting hash.

Routine MCP/orchestrator work uses `read_fast()`. Before a sidecar is trusted it
must match the authoritative JSONL file size/mtime, indexed last sequence/hash,
experiment definition hash, and sidecar schema. If the JSONL file changes outside
the normal indexed append path, the sidecar is rejected and rebuilt from a full
verified chain. Corrupt authoritative history therefore still fails closed.

## Append behavior

Normal causal mutations append one new JSONL record, fsync it, then transactionally
project that record into SQLite. If projection fails, JSONL remains authoritative;
the next fast read detects the stale sidecar and performs a verified rebuild.

Review batches no longer copy all historical JSONL bytes into a temporary file.
The validated review/rule records are hash-linked in memory and appended as one
batch under the experiment lock. An in-process write/fsync failure truncates back
to the original byte length. The sidecar batch update is one SQLite transaction.

## Weekly adaptive walk-forward impact

For a weekly adaptive experiment this keeps the common loop bounded:

1. read indexed head/current state;
2. query compact rule/candidate lifecycle data;
3. inspect the configured recent evidence windows;
4. record the weekly review and rule mutations by appending only new records;
5. checkpoint the resulting weekly state.

Historical evidence is retained for audit and long-horizon analytics without
making every new week pay the cost of reparsing all prior event history.

## Recovery

If `head.json`, `checkpoint.json`, or `event_index.sqlite3` is missing or
stale, no experiment data is lost. The next indexed read verifies
`events.jsonl`, reconstructs derived state, and rebuilds all sidecars.
