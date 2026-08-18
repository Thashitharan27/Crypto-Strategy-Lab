"""Temporary Stage 22 follow-up: migrate tests to conventional trade-R semantics."""
from pathlib import Path


def replace_once(path, old, new):
    p=Path(path); text=p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected Stage 22 fragment not found in {path}: {old}")
    p.write_text(text.replace(old,new,1),encoding="utf-8")

# Keep account-risk display deliberately fixed to two decimals for readability.
replace_once(
    "crypto_strategy_lab/gui/main_window.py",
    'self.risk_warn.setText(f"Base {format_percentage(r,2)} × {profile_name} {multiplier:g}x = {format_percentage(planned,2)} account risk (${planned_cash:,.2f} at ${self.equity.value():,.2f} equity)" + (" — warning: exceeds 5%." if planned>0.05 else ""))',
    'self.risk_warn.setText(f"Base {r*100:.2f}% × {profile_name} {multiplier:g}x = {planned*100:.2f}% account risk (${planned_cash:,.2f} at ${self.equity.value():,.2f} equity)" + (" — warning: exceeds 5%." if planned>0.05 else ""))',
)

# Stage 22 intentionally changes these from base-distance normalization to full-stop trade R.
replace_once("tests/test_partial_take_profit.py", "assert position.sl == pytest.approx(105)", "assert position.sl == pytest.approx(110)")
replace_once("tests/test_partial_take_profit.py", "assert position.stop_exit_price == pytest.approx(105)", "assert position.stop_exit_price == pytest.approx(110)")
replace_once("tests/test_partial_stop_loss.py", "assert weighted_price_r(position) == pytest.approx(-1.25)", "assert weighted_price_r(position) == pytest.approx(-0.625)")
replace_once("tests/test_partial_stop_loss.py", "assert weighted_price_r(position) == pytest.approx(1.75)", "assert weighted_price_r(position) == pytest.approx(0.875)")
