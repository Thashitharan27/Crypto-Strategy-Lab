"""Temporary Stage 24 migration: reorganize the Support & Resistance GUI without changing engine behavior."""
from pathlib import Path

path = Path("crypto_strategy_lab/gui/main_window.py")
text = path.read_text(encoding="utf-8")

build_start = text.index("    def _build_support_resistance_tab(self):")
usage_start = text.index("    def _update_sr_usage_radios(self):", build_start)
state_start = text.index("    def _update_sr_tab_state(self):", usage_start)
next_def = text.index("    def _build_di_strategy_tab(self):", state_start)

new_build = '''    def _build_support_resistance_tab(self):
        page=QWidget(); outer=QVBoxLayout(page); scroll=QScrollArea(); scroll.setWidgetResizable(True); inner=QWidget(); layout=QVBoxLayout(inner)

        usage=QGroupBox("Support & Resistance"); usage_layout=QVBoxLayout(usage)
        self.enable_support_resistance_analysis.setText("Enable Support & Resistance")
        self.enable_support_resistance_analysis.setToolTip("Calculate, store, and report support/resistance context.")
        usage_layout.addWidget(self.enable_support_resistance_analysis)
        usage_layout.addWidget(QLabel("Usage"))
        self.sr_analyze_only=QRadioButton("Analyze Only")
        self.sr_apply_entry_rules=QRadioButton("Filter Entries")
        usage_layout.addWidget(self.sr_analyze_only)
        analysis_help=QLabel("Record S/R context and reports. This mode never rejects trades."); analysis_help.setWordWrap(True); usage_layout.addWidget(analysis_help)
        usage_layout.addWidget(self.sr_apply_entry_rules)
        filter_help=QLabel("Use the selected LONG/SHORT rules below to reject entries."); filter_help.setWordWrap(True); usage_layout.addWidget(filter_help)
        self.sr_strategy_status=QLabel(); self.sr_strategy_status.setWordWrap(True)
        self.sr_strategy_status.setStyleSheet("font-weight: 600; padding: 4px;")
        usage_layout.addWidget(self.sr_strategy_status)
        layout.addWidget(usage)

        entry_box=QGroupBox("Entry Filters"); entry_layout=QVBoxLayout(entry_box)
        columns=QHBoxLayout(); long_box=QGroupBox("LONG"); lf=QFormLayout(long_box); short_box=QGroupBox("SHORT"); sf=QFormLayout(short_box)
        self.sr_long_avoid_near_resistance.setText("Avoid entry near resistance")
        self.sr_long_require_near_support.setText("Require entry near support")
        self.sr_long_block_broken_support.setText("Reject after support break")
        self.sr_short_avoid_near_support.setText("Avoid entry near support")
        self.sr_short_require_near_resistance.setText("Require entry near resistance")
        self.sr_short_block_broken_resistance.setText("Reject after resistance break")
        self.sr_long_avoid_near_resistance.setToolTip("Reject LONG entries when price is near resistance.")
        self.sr_long_require_near_support.setToolTip("Allow LONG entries only when price is near support.")
        self.sr_short_avoid_near_support.setToolTip("Reject SHORT entries when price is near support.")
        self.sr_short_require_near_resistance.setToolTip("Allow SHORT entries only when price is near resistance.")
        self.sr_long_min_room_to_resistance_atr.setSuffix(" ATR"); self.sr_short_min_room_to_support_atr.setSuffix(" ATR")
        lf.addRow(self.sr_long_require_near_support); lf.addRow(self.sr_long_avoid_near_resistance); lf.addRow(self.sr_long_block_broken_support); lf.addRow("Minimum room to resistance", self.sr_long_min_room_to_resistance_atr)
        sf.addRow(self.sr_short_require_near_resistance); sf.addRow(self.sr_short_avoid_near_support); sf.addRow(self.sr_short_block_broken_resistance); sf.addRow("Minimum room to support", self.sr_short_min_room_to_support_atr)
        columns.addWidget(long_box); columns.addWidget(short_box); entry_layout.addLayout(columns)
        self.sr_trade_context_note=QLabel("Analyze Only is active. Entry filters are saved but do not reject trades."); self.sr_trade_context_note.setWordWrap(True); entry_layout.addWidget(self.sr_trade_context_note)
        self.sr_entry_rules_box=entry_box; layout.addWidget(entry_box)

        proximity=QGroupBox("Price Proximity"); pf=QFormLayout(proximity)
        self.sr_near_distance_atr.setSuffix(" ATR")
        self.sr_near_distance_atr.setToolTip("Price within this ATR distance of the closest S/R zone is considered near that level.")
        pf.addRow("Near-Level Distance",self.sr_near_distance_atr)
        proximity_help=QLabel("Defines when price is classified as near the closest support or resistance zone."); proximity_help.setWordWrap(True); pf.addRow("",proximity_help)
        self.sr_proximity_box=proximity; layout.addWidget(proximity)

        interaction=QGroupBox("Level Interaction"); interaction_layout=QVBoxLayout(interaction)
        hold_widget=QWidget(); hf=QFormLayout(hold_widget); hf.setContentsMargins(0,0,0,0)
        self.enable_sr_hold_confirmation.setText("Confirm level hold after a test")
        self.enable_sr_hold_confirmation.setToolTip("After price tests a zone, mark it HELD only after sufficient rejection within the confirmation window. This does not control when a level is marked BROKEN.")
        self.sr_hold_confirmation_bars.setToolTip("Maximum candles after a zone test in which the required rejection may confirm that the level held.")
        self.sr_hold_confirmation_atr.setToolTip("Minimum rejection away from the tested zone required to classify the level as held.")
        self.sr_hold_confirmation_atr.setSuffix(" ATR")
        hf.addRow(self.enable_sr_hold_confirmation); hf.addRow("Confirmation Window",self.sr_hold_confirmation_bars); hf.addRow("Required Rejection",self.sr_hold_confirmation_atr)
        interaction_layout.addWidget(hold_widget)
        break_box=QGroupBox("Break Detection"); bf=QFormLayout(break_box)
        self.sr_break_basis.setToolTip("Use candle closes or wicks to decide whether price has moved beyond a zone far enough to mark it broken.")
        self.sr_break_tolerance_atr.setToolTip("ATR distance beyond the zone required before the structure is marked broken.")
        self.sr_break_tolerance_atr.setSuffix(" ATR")
        bf.addRow("Break Basis",self.sr_break_basis); bf.addRow("Break Tolerance",self.sr_break_tolerance_atr)
        interaction_layout.addWidget(break_box)
        self.sr_interaction_box=interaction; self.sr_break_detection_box=interaction; layout.addWidget(interaction)

        detection=QGroupBox("Level Detection"); detection_layout=QVBoxLayout(detection)
        preset_row=QFormLayout(); self.sr_detection_preset=QComboBox(); self.sr_detection_preset.addItems(["Conservative","Balanced (Recommended)","Sensitive","Custom"]); self.sr_detection_preset.setCurrentText("Balanced (Recommended)")
        preset_row.addRow("Detection Sensitivity",self.sr_detection_preset); detection_layout.addLayout(preset_row)
        preset_help=QLabel("Use a preset for normal testing. Raw pivot settings are available below for deliberate research only."); preset_help.setWordWrap(True); detection_layout.addWidget(preset_help)
        self.sr_detection_advanced=QGroupBox("Advanced Detection Settings"); self.sr_detection_advanced.setCheckable(True); self.sr_detection_advanced.setChecked(False)
        af=QFormLayout(); self.sr_zone_width_atr.setSuffix(" ATR"); self.sr_zone_width_atr.setToolTip("Merge nearby detected swing levels into one zone when they are within this ATR distance.")
        af.addRow("Pivot Left",self.sr_pivot_left); af.addRow("Pivot Right",self.sr_pivot_right); af.addRow("Lookback Bars",self.sr_lookback_bars); af.addRow("Zone Merge Width",self.sr_zone_width_atr)
        advanced_content=QWidget(); advanced_content.setLayout(af); advanced_wrapper=QVBoxLayout(self.sr_detection_advanced); advanced_wrapper.addWidget(advanced_content); self.sr_detection_advanced.toggled.connect(advanced_content.setVisible); advanced_content.setVisible(False)
        detection_layout.addWidget(self.sr_detection_advanced)
        self.sr_detection_box=detection; self.sr_advanced_box=detection; layout.addWidget(detection)

        summary=QGroupBox("Current Configuration"); sl=QVBoxLayout(summary); self.sr_summary_label=QLabel(); self.sr_summary_label.setWordWrap(True); sl.addWidget(self.sr_summary_label); layout.addWidget(summary); layout.addStretch(1)
        self._sr_detection_presets={"Conservative":{"pivot_left":8,"pivot_right":8,"lookback":300,"zone_width_atr":0.75,"break_tolerance_atr":0.35},"Balanced (Recommended)":{"pivot_left":5,"pivot_right":5,"lookback":200,"zone_width_atr":0.5,"break_tolerance_atr":0.25},"Sensitive":{"pivot_left":3,"pivot_right":3,"lookback":150,"zone_width_atr":0.35,"break_tolerance_atr":0.15}}
        self.sr_detection_preset.currentTextChanged.connect(self._apply_sr_detection_preset)
        for c in (self.sr_pivot_left,self.sr_pivot_right,self.sr_lookback_bars,self.sr_zone_width_atr,self.sr_break_tolerance_atr): c.valueChanged.connect(self._mark_sr_preset_custom)
        self.sr_analyze_only.toggled.connect(lambda checked: checked and self.sr_filter_mode.setCurrentText("ANALYSIS_ONLY")); self.sr_apply_entry_rules.toggled.connect(lambda checked: checked and self.sr_filter_mode.setCurrentText("APPLY_ENTRY_RULES"))
        for c in (self.enable_support_resistance_analysis,self.enable_sr_hold_confirmation,self.sr_analyze_only,self.sr_apply_entry_rules): c.toggled.connect(self.update_dynamic)
        for c in (self.sr_filter_mode,self.sr_break_basis): c.currentTextChanged.connect(self.update_dynamic)
        for c in (self.sr_near_distance_atr,self.sr_zone_width_atr,self.sr_hold_confirmation_bars,self.sr_hold_confirmation_atr,self.sr_break_tolerance_atr,self.sr_pivot_left,self.sr_pivot_right,self.sr_lookback_bars): c.valueChanged.connect(self.update_dynamic)
        for c in (self.sr_long_avoid_near_resistance,self.sr_long_require_near_support,self.sr_long_block_broken_support,self.sr_short_avoid_near_support,self.sr_short_require_near_resistance,self.sr_short_block_broken_resistance): c.toggled.connect(self.update_dynamic)
        for c in (self.sr_long_min_room_to_resistance_atr,self.sr_short_min_room_to_support_atr): c.valueChanged.connect(self.update_dynamic)
        outer.addWidget(scroll); scroll.setWidget(inner); self.tabs.addTab(page,"Support & Resistance"); self._update_sr_usage_radios(); self._update_sr_tab_state()

'''

old_middle = text[usage_start:state_start]
# Keep _update_sr_usage_radios, preset application, custom tracking, and sync helpers,
# while migrating the Balanced preset display name used by the GUI.
old_middle = old_middle.replace('self.sr_filter_mode.currentText()=="ANALYSIS_ONLY"', 'self.sr_filter_mode.currentText()=="ANALYSIS_ONLY"')

new_state = '''    def _update_sr_tab_state(self):
        if not hasattr(self,"sr_summary_label"): return
        self._update_sr_usage_radios()
        enabled=self.enable_support_resistance_analysis.isChecked()
        applying=self.sr_filter_mode.currentText()!="ANALYSIS_ONLY"
        self.sr_analyze_only.setEnabled(enabled); self.sr_apply_entry_rules.setEnabled(enabled)
        for box in (self.sr_proximity_box,self.sr_interaction_box,self.sr_detection_box): box.setEnabled(enabled)
        self.sr_entry_rules_box.setEnabled(enabled and applying)
        confirmation=enabled and self.enable_sr_hold_confirmation.isChecked()
        self.sr_hold_confirmation_bars.setEnabled(confirmation); self.sr_hold_confirmation_atr.setEnabled(confirmation)
        if not enabled:
            note="Support & Resistance is disabled."
            impact="DISABLED"
        elif not applying:
            note="Analyze Only is active. Entry filters are saved but do not reject trades."
            impact="NONE — ANALYSIS ONLY"
        else:
            note="Filter Entries is active. Selected LONG/SHORT rules may reject entries."
            impact="ENTRY FILTER ACTIVE"
        self.sr_trade_context_note.setText(note)
        self.sr_strategy_status.setText(f"Trading impact: {impact}")
        long_rules=[label for c,label in ((self.sr_long_require_near_support,"Require near support"),(self.sr_long_avoid_near_resistance,"Avoid near resistance"),(self.sr_long_block_broken_support,"Reject after support break")) if c.isChecked()]
        short_rules=[label for c,label in ((self.sr_short_require_near_resistance,"Require near resistance"),(self.sr_short_avoid_near_support,"Avoid near support"),(self.sr_short_block_broken_resistance,"Reject after resistance break")) if c.isChecked()]
        if self.sr_long_min_room_to_resistance_atr.value() > 0: long_rules.append(f"Minimum room {self.sr_long_min_room_to_resistance_atr.value():.2f} ATR")
        if self.sr_short_min_room_to_support_atr.value() > 0: short_rules.append(f"Minimum room {self.sr_short_min_room_to_support_atr.value():.2f} ATR")
        long_text=", ".join(long_rules) or "None"
        short_text=", ".join(short_rules) or "None"
        mode="Filter Entries" if applying else "Analyze Only"
        preset=self.sr_detection_preset.currentText()
        self.sr_summary_label.setText(
            f"Mode: {mode}\n"
            f"Detection: {preset}\n"
            f"Near level: ≤ {self.sr_near_distance_atr.value():.2f} ATR\n\n"
            f"LONG filters: {long_text}\n"
            f"SHORT filters: {short_text}"
        )

'''

text = text[:build_start] + new_build + old_middle + new_state + text[next_def:]
path.write_text(text, encoding="utf-8")
