# OpenAI Batch cache workflow

The AI direction strategy has an offline Batch API workflow so historical backtests do not make synchronous API calls while the simulator is running.

## Why it is separate from the simulator

The simulator remains deterministic and cache-driven. Historical AI generation is a preprocessing step:

1. **Prepare** causal snapshots into Batch API JSONL request files. This makes no OpenAI API call and spends nothing.
2. **Submit** one or more prepared files to OpenAI Batch API.
3. **Collect** completed output and validate every LONG/SHORT decision into `ai_decision_cache.jsonl`.
4. Run the normal backtest in `CACHE_ONLY` mode.

This keeps model generation, network errors, and asynchronous completion outside the execution engine.

## Current Batch limits

The generator splits work before OpenAI's current per-batch limits:

- maximum 50,000 requests in one batch
- maximum 200 MB input file
- local preparation defaults to a 190 MB safety ceiling
- Batch endpoint: `/v1/responses`
- completion window: `24h`

## Candidate over-generation

`WAIT_UNTIL_CLOSED` is path-dependent: the next real decision candle depends on when the previous AI-selected trade exits. It is therefore impossible to know the exact complete sequence of decision candles before any AI decisions exist.

The offline generator deliberately prepares a safe superset of **base-eligible** candles. The later simulator consumes only the cached decisions it actually needs. This may over-generate requests, especially on small timeframes.

For that reason **prepare and submit are separate commands**. Always inspect `candidate_count`, `prepared_count`, file count and byte size before submitting a large historical window.

## CLI

Use a saved current configuration that has `AI Decision — OpenAI` selected.

Prepare only (no API call):

```text
python -m crypto_strategy_lab.ai_batch_cli prepare --config path/to/config.json --output-dir output/ai_batches
```

Submit one prepared part:

```text
python -m crypto_strategy_lab.ai_batch_cli submit --request-file output/ai_batches/ai_direction_batch_001.jsonl
```

Check a submitted batch:

```text
python -m crypto_strategy_lab.ai_batch_cli status --batch-id batch_...
```

Collect completed output into the standard cache:

```text
python -m crypto_strategy_lab.ai_batch_cli collect \
  --batch-id batch_... \
  --manifest-file output/ai_batches/ai_direction_batch_001.manifest.jsonl \
  --cache output/ai_decision_cache.jsonl
```

`OPENAI_API_KEY` is required only for `submit`, `status`, and `collect`. It is not required for `prepare` and is never written into the request manifest or cache.

## Reproducibility

Every manifest row records:

- unique `custom_id`
- cache key
- snapshot hash
- model
- reasoning effort
- prompt version
- decision timestamp
- symbol
- strategy timeframe
- strategy index when generated from an engine

Batch result order is not trusted. Collection maps each returned row by `custom_id`, validates that LONG + SHORT confidence equals 100, rejects 50/50 ties, and only then appends the decision to the normal cache.

Market-permission flags such as a profile's `enabled` state are stripped before hashing or submission. The model therefore scores both LONG and SHORT from market evidence, while deterministic permissions remain downstream execution policy.
