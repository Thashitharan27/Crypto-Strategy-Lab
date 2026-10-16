# Phase 1b: read-only trade CSV parity adapter

`crypto_strategy_lab.trade_parity_artifacts` reads existing `trade_list.csv` files without modification. Use an **explicit mapping** from every parity field to one source CSV column. The adapter rejects missing or empty execution fields; it never fills missing signals, stop/target, fees or PnL with zero. After adapting two reports, it invokes the independent `compare_trades` implementation from PR #503.

**Important:** this module does not claim existing run artifacts have all these columns. Before comparing historical data, first inventory their exact schemas and semantics. In particular, report-level `pair_net_pnl` or `pair_net_r` must not be substituted for leg-level PnL/R without an explicit documented normalization choice. A trade-list row may aggregate multiple legs, so unique trade identity and fee semantics must also be reviewed. Capture run manifest, config snapshot, data hash, code commit and timeframes as part of the future baseline.

This PR is a dependent test utility, not a verified golden backtest and not an execution-path change. Merge only after PR #503 is merged, its branch dependency has been resolved, and all required checks pass.

## Read-only Windows comparison handoff

From the original Windows checkout, after verifying that two independently produced
CSV reports have equivalent **leg-level** semantics and stable unique trade IDs:

```powershell
python tools/inspect_parity_trade_report.py "C:\\path\\to\\original\\trade_list.csv"
python tools/inspect_parity_trade_report.py "C:\\path\\to\\replay\\trade_list.csv"
python tools/compare_frozen_trade_csv.py "C:\\path\\to\\original\\trade_list.csv" "C:\\path\\to\\replay\\trade_list.csv" --mapping "C:\\path\\to\\verified_mapping.json"
```

The mapping JSON must have **all 15 normalized trade fields** as keys, each
mapped to a distinct native CSV column. Validate column semantics rather than
inventing missing fields. Preserve the emitted SHA-256 hashes, CLI JSON output,
exit code and exact main commit alongside the frozen data/configuration hashes.
The default numeric tolerance is zero, with exact decimal verification for
source CSV fields. Exit 0 means **only** that the mapped row projection agrees;
exit 1 means mismatches. The output explicitly sets
`historical_execution_certified: false` even for `status: PASS`.

This is **not** a full replay or a Phase 5 release certificate. It does not
compare individual TP1/SL1/TP2 fills, BE/trailing event histories, intraminute
order or equity sequences unless those are represented in separately verified
independent evidence. A true Fibonacci pending-limit reference must be an
original executed fixture; otherwise record
`ORIGINAL_FIB_EXECUTION_FIXTURE_MISSING`. Do not write to original files,
rebuild canonical data, merge PR #501, or enable browser execution/config writes.
