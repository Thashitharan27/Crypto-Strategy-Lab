# Phase 1b: read-only trade CSV parity adapter

`crypto_strategy_lab.trade_parity_artifacts` reads existing `trade_list.csv` files without modification. Use an **explicit mapping** from every parity field to one source CSV column. The adapter rejects missing or empty execution fields; it never fills missing signals, stop/target, fees or PnL with zero. After adapting two reports, it invokes the independent `compare_trades` implementation from PR #503.

**Important:** this module does not claim existing run artifacts have all these columns. Before comparing historical data, first inventory their exact schemas and semantics. In particular, report-level `pair_net_pnl` or `pair_net_r` must not be substituted for leg-level PnL/R without an explicit documented normalization choice. A trade-list row may aggregate multiple legs, so unique trade identity and fee semantics must also be reviewed. Capture run manifest, config snapshot, data hash, code commit and timeframes as part of the future baseline.

This PR is a dependent test utility, not a verified golden backtest and not an execution-path change. Merge only after PR #503 is merged, its branch dependency has been resolved, and all required checks pass.
