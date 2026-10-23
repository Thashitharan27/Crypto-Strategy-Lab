# DI partial at 1R and optional cost-cover ATR adjustment

Select **DI Direction**, then open Risk / Execution → Optional Trade Management.
Both new options default off and are saved per execution profile:

- **DI: close partial at 1R and move SL to entry** closes the chosen percentage
  of the original quantity at one actual entry-to-initial-SL distance of profit.
  The percentage defaults to 10%, adjustable strictly between 0% and 100%.
  The remainder's SL moves to the actual entry price for subsequent execution
  candles. The final target uses the configured reward/risk ratio, which must
  exceed 1R, using the fixed reward/risk target policy. Other partial, BE and trailing protection modes are disabled while
  this preset is active; timeout remains available.
- **Increase ATR distance so the 1R partial covers estimated costs** is available
  with the first option and ATR risk mode. It increases the price risk distance
  only when necessary, never tightening a wider existing stop. The target remains
  at the configured R multiple of the adjusted distance. Position quantity is
  recalculated from the adjusted actual stop, retaining the geometric sizing
  budget; separate sizing-stop overrides are incompatible with this option.

For fraction f, actual filled entry E, direction s (+1 long, −1 short), entry fee
rate a, exit fee rate b and slippage z, let u = 1 − sz. The minimum price distance
is E(z + ub + a) / [fu(1 − sb)]. Use the greater of this minimum and the existing
ATR stop distance. This solves for the partial exit plus remaining quantity
stopped at entry to have zero net P&L under the native fee/slippage model.
Entry slippage is already reflected in E; the new partial exit and remaining BE
exit both receive configured adverse exit slippage. Maker/taker selections use
the same rates as the simulator's fills. Stop gaps, future funding and exchange
rounding are not guaranteed covered.

The first option alone does **not** guarantee costs are covered: a small ATR stop
may produce too little profit from a 10% partial. With adjustment enabled, larger
partial percentages generally require less distance. Zero-cost runs retain the
existing ATR distance. Impractically small percentages that require nonpositive
price levels are rejected.

An existing stop wins an ambiguous stop/TP1 candle under pessimistic ordering.
The newly moved BE stop never acts earlier within the candle that filled TP1.
Only the original remaining quantity is closed at TP2, timeout or BE. Normal
partial-fill fees, funding accounting and original-R result units are retained.

Result rows add `di_partial_1r_enabled`, `di_partial_cost_atr_enabled`,
`di_partial_original_stop_distance`, `di_partial_minimum_cost_stop_distance`, and
`di_partial_effective_atr_multiplier`. Existing TP1/TP2 quantities, actual fills,
fees, remaining quantity and BE history retain the realized execution details.
