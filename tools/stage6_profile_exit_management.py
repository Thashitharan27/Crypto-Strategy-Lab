from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing pattern for {label}")
    return text.replace(old, new, 1)

# 1) StrategyProfile: make the two special exit managers profile-owned.
p = ROOT / "crypto_strategy_lab/strategy_profiles.py"
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    "    timeout_enabled: bool = False\n    timeout_minutes: int = 480\n",
    "    timeout_enabled: bool = False\n    timeout_minutes: int = 480\n"
    "    r_step_trailing_enabled: bool = False\n"
    "    r_step_activation_r: float = 2.0\n"
    "    r_step_distance_r: float = 2.0\n"
    "    r_step_size_r: float = 1.0\n"
    "    r_step_maximum_r: float = 0.0\n"
    "    r_step_activation_close_pct: float = 0.0\n"
    "    atr_checkpoint_tp_extension_enabled: bool = False\n"
    "    atr_checkpoint_di_spread_minimum: float = 30.0\n"
    "    atr_checkpoint_bb_width_minimum: float = 0.03\n"
    "    atr_checkpoint_profit_lock_start: float = 3.0\n"
    "    atr_checkpoint_profit_lock_distance: float = 1.0\n",
    "profile exit fields",
)
s = replace_once(
    s,
    "        if self.break_even_activation_r <= 0: raise ValueError(f\"{key}: break-even activation must be positive\")\n",
    "        if self.break_even_activation_r <= 0: raise ValueError(f\"{key}: break-even activation must be positive\")\n"
    "        if self.r_step_activation_r <= 0 or self.r_step_distance_r <= 0 or self.r_step_size_r <= 0: raise ValueError(f\"{key}: R-step distances must be positive\")\n"
    "        if self.r_step_maximum_r < 0: raise ValueError(f\"{key}: R-step maximum cannot be negative\")\n"
    "        if not 0 <= self.r_step_activation_close_pct < 100: raise ValueError(f\"{key}: R-step activation close must be from 0% up to, but not including, 100%\")\n"
    "        if self.atr_checkpoint_di_spread_minimum < 0 or self.atr_checkpoint_bb_width_minimum < 0: raise ValueError(f\"{key}: checkpoint thresholds cannot be negative\")\n"
    "        if self.atr_checkpoint_profit_lock_start <= 0 or self.atr_checkpoint_profit_lock_distance <= 0: raise ValueError(f\"{key}: checkpoint profit-lock values must be positive\")\n"
    "        if self.r_step_trailing_enabled and self.trailing_enabled: raise ValueError(f\"{key}: choose either R-step staircase or trailing stop\")\n"
    "        if self.r_step_trailing_enabled and self.partial_profit_enabled: raise ValueError(f\"{key}: R-step staircase cannot be combined with partial take-profit\")\n"
    "        if self.r_step_trailing_enabled and self.atr_checkpoint_tp_extension_enabled: raise ValueError(f\"{key}: choose either R-step staircase or ATR checkpoint extension\")\n",
    "profile exit validation",
)
p.write_text(s, encoding="utf-8")

# 2) Profile editor: expose the controls where users actually configure profiles.
p = ROOT / "crypto_strategy_lab/gui/profile_editor.py"
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    "        self._check(\"timeout_enabled\",\"Maximum holding time\"); self._integer(\"timeout_minutes\",480,1,1000000)\n",
    "        self._check(\"timeout_enabled\",\"Maximum holding time\"); self._integer(\"timeout_minutes\",480,1,1000000)\n"
    "        self._check(\"r_step_trailing_enabled\",\"R-step staircase\"); self._number(\"r_step_activation_r\",2,.001,1000); self._number(\"r_step_distance_r\",2,.001,1000); self._number(\"r_step_size_r\",1,.001,1000); self._number(\"r_step_maximum_r\",0,0,1000); self._number(\"r_step_activation_close_pct\",0,0,99.99)\n"
    "        self._check(\"atr_checkpoint_tp_extension_enabled\",\"ATR checkpoint TP extension\"); self._number(\"atr_checkpoint_di_spread_minimum\",30,0,1000); self._number(\"atr_checkpoint_bb_width_minimum\",.03,0,1000); self._number(\"atr_checkpoint_profit_lock_start\",3,.001,1000); self._number(\"atr_checkpoint_profit_lock_distance\",1,.001,1000)\n",
    "profile editor controls",
)
s = replace_once(
    s,
    "        self.controls[\"timeout_minutes\"].setToolTip(\"480 minutes equals 8 hours.\")\n",
    "        self.controls[\"timeout_minutes\"].setToolTip(\"480 minutes equals 8 hours.\")\n"
    "        for key,label in ((\"r_step_activation_r\",\"Staircase activation\"),(\"r_step_distance_r\",\"Stop distance behind checkpoint\"),(\"r_step_size_r\",\"Checkpoint step\"),(\"r_step_maximum_r\",\"Maximum target (0 = runner)\"),(\"r_step_activation_close_pct\",\"Close at activation\"),(\"atr_checkpoint_di_spread_minimum\",\"Checkpoint DI spread minimum\"),(\"atr_checkpoint_bb_width_minimum\",\"Checkpoint BB width minimum\"),(\"atr_checkpoint_profit_lock_start\",\"Profit lock starts at\"),(\"atr_checkpoint_profit_lock_distance\",\"Profit lock distance\")):\n"
    "            self.form.labelForField(self.controls[key]).setText(label)\n"
    "        for key in (\"r_step_activation_r\",\"r_step_distance_r\",\"r_step_size_r\",\"r_step_maximum_r\",\"atr_checkpoint_profit_lock_start\",\"atr_checkpoint_profit_lock_distance\"):\n"
    "            self.controls[key].setSuffix(\" R\")\n"
    "        self.controls[\"r_step_activation_close_pct\"].setSuffix(\" %\")\n"
    "        self.controls[\"atr_checkpoint_bb_width_minimum\"].setDecimals(6)\n",
    "profile editor labels",
)
s = replace_once(
    s,
    "        for key in (\"partial_stop_enabled\",\"partial_profit_enabled\",\"trailing_enabled\",\"break_even_enabled\",\"timeout_enabled\"): self.controls[key].toggled.connect(self._update_management_controls)\n",
    "        for key in (\"partial_stop_enabled\",\"partial_profit_enabled\",\"trailing_enabled\",\"break_even_enabled\",\"timeout_enabled\",\"r_step_trailing_enabled\",\"atr_checkpoint_tp_extension_enabled\"): self.controls[key].toggled.connect(self._update_management_controls)\n",
    "profile editor dynamic signals",
)
p.write_text(s, encoding="utf-8")

# 3) Position: store the chosen profile settings on each trade so later exits never
#    depend on whatever global/profile object happens to be current.
p = ROOT / "crypto_strategy_lab/trade.py"
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    "    atr_checkpoint_extension_enabled: bool = False; atr_checkpoint_next_r: float = 1.0; atr_checkpoint_count: int = 0;",
    "    atr_checkpoint_extension_enabled: bool = False; atr_checkpoint_di_spread_minimum: float = 30.0; atr_checkpoint_bb_width_minimum: float = 0.03; atr_checkpoint_profit_lock_start: float = 3.0; atr_checkpoint_profit_lock_distance: float = 1.0; atr_checkpoint_next_r: float = 1.0; atr_checkpoint_count: int = 0;",
    "position checkpoint settings",
)
s = replace_once(
    s,
    "    r_step_trailing_enabled: bool = False; r_step_trailing_active: bool = False; r_step_next_checkpoint_r: float = 2.0;",
    "    r_step_trailing_enabled: bool = False; r_step_activation_r: float = 2.0; r_step_distance_r: float = 2.0; r_step_size_r: float = 1.0; r_step_maximum_r: float = 0.0; r_step_trailing_active: bool = False; r_step_next_checkpoint_r: float = 2.0;",
    "position staircase settings",
)
p.write_text(s, encoding="utf-8")

# 4) Engine: profile settings are authoritative for the selected profile. Global
#    values remain only as a non-profile fallback for this migration stage.
p = ROOT / "crypto_strategy_lab/engine.py"
s = p.read_text(encoding="utf-8")
old = '''            pos.atr_checkpoint_extension_enabled = bool(\n                self.config.enable_atr_checkpoint_tp_extension\n                and sizing_direction == pos.side.value\n            )\n            if pos.atr_checkpoint_extension_enabled:\n                pos.atr_checkpoint_initial_tp = pos.tp\n                pos.atr_checkpoint_final_tp_r = (long_target_distance if pos.side == Side.LONG else short_target_distance) / r\n            pos.r_step_trailing_enabled = bool(\n                self.config.enable_bull_long_r_step_trailing\n                and pos.side == Side.LONG\n                and applied_regime == "BULL"\n                and long_reward_risk + 1e-12 >= self.config.bull_long_r_step_activation_r\n            )\n            if pos.r_step_trailing_enabled:\n                pos.r_step_next_checkpoint_r = self.config.bull_long_r_step_activation_r\n                pos.r_step_initial_tp = pos.tp\n                pos.r_step_activation_close_pct = self.config.bull_long_r_step_activation_close_pct\n                if pos.r_step_activation_close_pct > 0:\n                    pos.partial_tp_enabled = True\n                    pos.original_quantity = pos.quantity\n                    pos.remaining_quantity = pos.quantity\n                    pos.tp1_quantity = pos.quantity * pos.r_step_activation_close_pct / 100.0\n                    pos.tp1_price = pos.entry_price + self.config.bull_long_r_step_activation_r * pos.risk\n                    pos.r_step_activation_quantity = pos.tp1_quantity\n                    pos.r_step_runner_quantity = pos.quantity - pos.tp1_quantity\n                if self.config.bull_long_r_step_maximum_r > 0:\n                    pos.tp = pos.entry_price + self.config.bull_long_r_step_maximum_r * pos.risk\n'''
new = '''            profile_for_special_exit = active_profile if active_profile is not None and pos.side.value == sizing_direction else None\n            pos.atr_checkpoint_extension_enabled = bool(\n                profile_for_special_exit.atr_checkpoint_tp_extension_enabled\n                if profile_for_special_exit else (self.config.enable_atr_checkpoint_tp_extension and sizing_direction == pos.side.value)\n            )\n            if pos.atr_checkpoint_extension_enabled:\n                pos.atr_checkpoint_di_spread_minimum = profile_for_special_exit.atr_checkpoint_di_spread_minimum if profile_for_special_exit else self.config.atr_checkpoint_di_spread_minimum\n                pos.atr_checkpoint_bb_width_minimum = profile_for_special_exit.atr_checkpoint_bb_width_minimum if profile_for_special_exit else self.config.atr_checkpoint_bb_width_minimum\n                pos.atr_checkpoint_profit_lock_start = profile_for_special_exit.atr_checkpoint_profit_lock_start if profile_for_special_exit else self.config.atr_checkpoint_profit_lock_start\n                pos.atr_checkpoint_profit_lock_distance = profile_for_special_exit.atr_checkpoint_profit_lock_distance if profile_for_special_exit else self.config.atr_checkpoint_profit_lock_distance\n                pos.atr_checkpoint_initial_tp = pos.tp\n                pos.atr_checkpoint_final_tp_r = (long_target_distance if pos.side == Side.LONG else short_target_distance) / r\n            pos.r_step_trailing_enabled = bool(\n                profile_for_special_exit.r_step_trailing_enabled\n                if profile_for_special_exit else (self.config.enable_bull_long_r_step_trailing and pos.side == Side.LONG and applied_regime == "BULL")\n            )\n            if pos.r_step_trailing_enabled:\n                pos.r_step_activation_r = profile_for_special_exit.r_step_activation_r if profile_for_special_exit else self.config.bull_long_r_step_activation_r\n                pos.r_step_distance_r = profile_for_special_exit.r_step_distance_r if profile_for_special_exit else self.config.bull_long_r_step_distance_r\n                pos.r_step_size_r = profile_for_special_exit.r_step_size_r if profile_for_special_exit else self.config.bull_long_r_step_size_r\n                pos.r_step_maximum_r = profile_for_special_exit.r_step_maximum_r if profile_for_special_exit else self.config.bull_long_r_step_maximum_r\n                pos.r_step_next_checkpoint_r = pos.r_step_activation_r\n                pos.r_step_initial_tp = pos.tp\n                pos.r_step_activation_close_pct = profile_for_special_exit.r_step_activation_close_pct if profile_for_special_exit else self.config.bull_long_r_step_activation_close_pct\n                if pos.r_step_activation_close_pct > 0:\n                    pos.partial_tp_enabled = True\n                    pos.original_quantity = pos.quantity\n                    pos.remaining_quantity = pos.quantity\n                    pos.tp1_quantity = pos.quantity * pos.r_step_activation_close_pct / 100.0\n                    pos.tp1_price = pos.entry_price + (1 if pos.side == Side.LONG else -1) * pos.r_step_activation_r * pos.risk\n                    pos.r_step_activation_quantity = pos.tp1_quantity\n                    pos.r_step_runner_quantity = pos.quantity - pos.tp1_quantity\n                if pos.r_step_maximum_r > 0:\n                    pos.tp = pos.entry_price + (1 if pos.side == Side.LONG else -1) * pos.r_step_maximum_r * pos.risk\n'''
s = replace_once(s, old, new, "engine special-exit initialization")
for old_name, new_name in (
    ("self.config.atr_checkpoint_di_spread_minimum", "pos.atr_checkpoint_di_spread_minimum"),
    ("self.config.atr_checkpoint_bb_width_minimum", "pos.atr_checkpoint_bb_width_minimum"),
    ("self.config.atr_checkpoint_profit_lock_start", "pos.atr_checkpoint_profit_lock_start"),
    ("self.config.atr_checkpoint_profit_lock_distance", "pos.atr_checkpoint_profit_lock_distance"),
    ("self.config.bull_long_r_step_maximum_r", "pos.r_step_maximum_r"),
    ("self.config.bull_long_r_step_activation_r", "pos.r_step_activation_r"),
    ("self.config.bull_long_r_step_distance_r", "pos.r_step_distance_r"),
    ("self.config.bull_long_r_step_size_r", "pos.r_step_size_r"),
):
    s = s.replace(old_name, new_name)
p.write_text(s, encoding="utf-8")

# 5) Regression tests focused on ownership and serialization.
p = ROOT / "tests/test_stage6_profile_exit_management.py"
p.write_text('''from dataclasses import asdict\n\nimport pytest\n\nfrom crypto_strategy_lab.strategy_profiles import StrategyProfile, normalize_profiles\nfrom crypto_strategy_lab.trade import Position, Side\n\n\ndef test_special_exit_management_is_profile_serializable():\n    profile = StrategyProfile(\n        enabled=True,\n        r_step_trailing_enabled=True,\n        r_step_activation_r=2.5,\n        r_step_distance_r=1.25,\n        r_step_size_r=0.5,\n        r_step_maximum_r=8.0,\n        r_step_activation_close_pct=20.0,\n    )\n    restored = normalize_profiles({"bull_long": asdict(profile)})["bull_long"]\n    assert restored.r_step_trailing_enabled is True\n    assert restored.r_step_activation_r == 2.5\n    assert restored.r_step_activation_close_pct == 20.0\n\n\ndef test_checkpoint_extension_is_profile_specific():\n    profiles = normalize_profiles({\n        "bull_long": {"enabled": True, "atr_checkpoint_tp_extension_enabled": True, "atr_checkpoint_di_spread_minimum": 35.0},\n        "bear_short": {"enabled": True},\n    })\n    assert profiles["bull_long"].atr_checkpoint_tp_extension_enabled is True\n    assert profiles["bull_long"].atr_checkpoint_di_spread_minimum == 35.0\n    assert profiles["bear_short"].atr_checkpoint_tp_extension_enabled is False\n\n\ndef test_conflicting_profile_exit_managers_are_rejected():\n    with pytest.raises(ValueError):\n        StrategyProfile(r_step_trailing_enabled=True, trailing_enabled=True).validate("bull_long")\n    with pytest.raises(ValueError):\n        StrategyProfile(r_step_trailing_enabled=True, atr_checkpoint_tp_extension_enabled=True).validate("bull_long")\n\n\ndef test_position_carries_profile_exit_parameters():\n    pos = Position(Side.LONG, None, 0, 100.0, 1.0, 98.0, 105.0, 1.0, 1.0, 100.0, 1.0)\n    pos.r_step_activation_r = 2.5\n    pos.atr_checkpoint_di_spread_minimum = 40.0\n    assert pos.r_step_activation_r == 2.5\n    assert pos.atr_checkpoint_di_spread_minimum == 40.0\n''', encoding="utf-8")

print("Stage 6 profile exit-management migration applied")
