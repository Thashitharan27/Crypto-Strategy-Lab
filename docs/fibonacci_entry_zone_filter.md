# Optional Fibonacci 50%–61.8% entry zone

Risk & Execution → Entry Execution → **Only enter inside the 50%–61.8% Fib zone**.
This is an execution filter for Fib Retracement Reaction, disabled by default.

The actual entry price, including slippage, must be strictly between the selected
signal swing's 50% and 61.8% level prices. For longs this means below the 50% price
and above the 61.8% price; shorts use the mirrored bounds. Exact boundaries fail.

Example: a long swing from 100 to 200 has 50% at 150 and 61.8% at 138.2. An entry
at 145 passes; entries at 150, 138.2, 155 or 130 fail. The decision uses entry
price, not the signal close or the name of the held Fib level.

Next-open entries use their actual next-open price after slippage. Deeper-limit
entries use their actual pending fill after slippage, with the original signal's
saved swing anchors. Missing/nonfinite anchors reject when enabled.

This filter does not create signals, move entry orders into the zone, wait for a
later price, or replace any existing confirmation, context, stop or target rule.
It can therefore reject otherwise valid reactions and exact-level limit fills.
It does not affect other strategies. Rejections are recorded as
`FIB_ENTRY_OUTSIDE_50_618_ZONE` or `FIB_ENTRY_ZONE_UNAVAILABLE`.

The setting is saved as `fib_entry_50_618_only`. Restart the tool, enable the
checkbox, and run a new backtest. Existing completed runs keep their trades.
