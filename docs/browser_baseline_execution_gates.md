# Browser migration: existing execution regression gates

This CI-only increment puts existing causal limit-order and pending-limit lifecycle tests into the blocking strategy-profile safety job. It reuses the tested Python execution path without rewriting the engine or duplicating Fibonacci limit handling.

The following pre-existing tests are intentionally added:
- `tests/test_engine_limit_entry_candidate.py`: pending limit price and expiration behavior;
- `tests/test_engine_limit_fill_schedule.py`: signal and fill index metadata, non-executing scheduling;
- `tests/test_engine_pending_limit_lifecycle.py`: pending candidate lifecycle.

These focused regressions **are not golden historical backtest results**. The next milestone requires a frozen BTCUSDT dataset with 1-minute execution files, canonical config/commit/data hashes and known trade outputs. Before parity certification, compare scheduled and actual entry timestamps, every leg and partial exit, fee model, reason codes and account R.

Do not merge PR #501 until the existing Fibonacci pending-limit machinery is checked for overlap and causal equivalence.
