# First 1-minute FVG confirmation

Select **Fair Value Gap** or **Fair Value Gap — Six Factors**, then open
**Risk & Execution → 1. Entry Execution** and click
**Use first 1m confirmation**.

The shortcut enables FVG confirmation, sets the confirmation candle to one
minute, selects one-minute intrabar data in Setup, and uses the next strategy
candle's open as the start of the confirmation window. Save the configuration
to reuse these settings. Existing saved confirmation durations remain unchanged
when loaded; the shortcut changes them only when clicked.

For a normal entry scheduled at 10:15, check the completed 10:15–10:16 candle:

- Long: close must be above open.
- Short: close must be below open.
- Opposite or doji candle: skip the setup, without checking later candles.

Enter at 10:16 using the confirmation close and configured slippage. Recheck
the existing stop and target-room requirements at that price. Fees, risk sizing,
FVG setup rules and target settings still apply. Intrabar exits begin at the
actual confirmed entry, not at the start of the confirmation candle.

The duration defaults to one minute for new configurations, with confirmation
disabled until selected. Other durations remain editable. Confirmation requires
an intrabar interval that divides the confirmation duration and a strategy
timeframe longer than the confirmation candle; scheduled daily entries are not
supported. The one-minute shortcut supplies the intrabar interval automatically.

Completed runs store the confirmation settings and actual entry timestamps.
Their visualizer/replay uses those delayed entries as usual.
