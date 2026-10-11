# Fibonacci: after two holds, enter one level deeper

Enable **After Two Holds — Enter One Fib Deeper** in the Fibonacci execution plan.
It replaces the former third-wick-retest behavior. The default remains OFF.
Saved configurations retain the `fib_third_retest_entry` key; enabling that key
now selects this replacement mode.

| Two separate holds confirmed at | Pending entry | Stop boundary |
| --- | --- | --- |
| 0.382 | 0.500 | 0.618 |
| 0.500 | 0.618 | 0.786 |
| 0.618 | 0.786 | 1.000 (original swing anchor) |

The existing clean-hold and separate-reaction rules establish two holds. Their
completed candle arms an order; that candle cannot fill it. A later price touch
fills without another candle confirmation. LONG uses a buy limit and SHORT a
sell limit. Opening gaps through the limit receive the opening price, subject
to existing execution slippage. A gap through the protective stop is rejected.

The structure and hold level are frozen at arming. A different selected impulse,
an impulse extension, a completed close past 0.786, or the end of the trading
window cancels the order. A level never reached produces no trade. Confirmation
inheritance and first-hold exceptions do not shorten the two-hold requirement.
This mode takes precedence over the optional 0.5 first-hold/swing-stop mode.
Direction flips are rejected for this native pending order.

SL buffers, fixed-R TP, impulse-target room checks, and position sizing use the
actual fill price and the stop boundary after the **entry** level. Fees and
slippage retain their existing settings. Intrabar data identifies the first
execution candle touching the limit. Without intrabar data the strategy OHLC is
used. Because OHLC cannot order the high and low inside a candle, the fill candle
conservatively allows protective stops but defers profitable extremes and
profit-based protection activation until a later execution candle.

Regression tests cover untouched orders, subsequent-bar fills, replacement
cancellation, SHORT gap fills, 0.786 entries with anchor stops, prefix causality,
and actual classic/prepared-engine sizing and intrabar execution.
