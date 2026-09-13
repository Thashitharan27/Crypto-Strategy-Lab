from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Patch anchor not found in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Legacy unit tests construct the rule engine with only `close` to test MACD.
# Keep that supported: EMA9/20 itself can be calculated, while ATR/volume-derived
# research arrays are only needed by a fully initialized backtest runtime.
patch(
    "crypto_strategy_lab/ema_pullback.py",
    "        self.ema_9_values = _signal_ema(self.close, 9)\n        self.ema_20_values = _signal_ema(self.close, 20)\n\n        previous_ema9 = np.roll(self.ema_9_values, 1)",
    "        self.ema_9_values = _signal_ema(self.close, 9)\n        self.ema_20_values = _signal_ema(self.close, 20)\n\n        if not hasattr(self, \"atr_values\") or not hasattr(self, \"volume\"):\n            return\n\n        previous_ema9 = np.roll(self.ema_9_values, 1)",
)

# The selector intentionally gains one new first-class signal strategy.
patch(
    "tests/test_rule_main_window.py",
    "        assert selector.count() == 3\n",
    "        assert selector.count() == 4\n",
)
patch(
    "tests/test_rule_main_window.py",
    "        assert selector.itemText(selector.findData(\"MACD_PULLBACK\")) == \"MACD Pullback — 12/26/9\"\n",
    "        assert selector.itemText(selector.findData(\"MACD_PULLBACK\")) == \"MACD Pullback — 12/26/9\"\n        assert selector.findData(\"EMA_9_20_PULLBACK\") >= 0\n        assert selector.itemText(selector.findData(\"EMA_9_20_PULLBACK\")) == \"EMA 9/20 Pullback — Scalping\"\n",
)

print("EMA 9/20 compatibility fixes applied")
