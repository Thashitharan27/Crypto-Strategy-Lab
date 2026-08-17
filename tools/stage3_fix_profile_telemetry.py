from pathlib import Path

path = Path('crypto_strategy_lab/engine.py')
text = path.read_text(encoding='utf-8')
old = '        pair.entry_atr_pct=float(self.atr_pct_values[ind_i]) if np.isfinite(self.atr_pct_values[ind_i]) else np.nan; pair.entry_rsi=float(self.directional_rsi_values[ind_i]) if np.isfinite(self.directional_rsi_values[ind_i]) else np.nan; pair.entry_close_location=float(self.close_location_values[ind_i]) if np.isfinite(self.close_location_values[ind_i]) else np.nan; pair.directional_momentum_return=float(self.directional_momentum_return_values[ind_i]) if np.isfinite(self.directional_momentum_return_values[ind_i]) else np.nan\n'
new = '''        pair.entry_atr_pct=float(self.atr_pct_values[ind_i]) if np.isfinite(self.atr_pct_values[ind_i]) else np.nan\n        pair.entry_close_location=float(self.close_location_values[ind_i]) if np.isfinite(self.close_location_values[ind_i]) else np.nan\n        if active_profile is not None:\n            profile_rsi=float(self.profile_rsi_values[active_profile.rsi_period][ind_i])\n            profile_momentum=float(self.profile_momentum_values[active_profile.momentum_lookback_hours][ind_i])\n            pair.entry_rsi=profile_rsi if np.isfinite(profile_rsi) else np.nan\n            pair.directional_momentum_return=profile_momentum if np.isfinite(profile_momentum) else np.nan\n        else:\n            pair.entry_rsi=np.nan\n            pair.directional_momentum_return=np.nan\n'''
if old not in text:
    raise SystemExit('expected legacy telemetry line not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
