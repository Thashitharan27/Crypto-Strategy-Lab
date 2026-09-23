"""Researcher-facing DI ladder rule workspace.

This is a friendly editor over ExecutionConfig.di_ladder_layers.  The simulator
contract remains unchanged: every layer owns a flat list of positive entry
conditions combined by ALL (AND) or ANY (OR).  The workspace stores the exact
native rule dictionaries consumed by di_ladder.py, so save/load and MCP/config
round-tripping remain lossless.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from crypto_strategy_lab.strategy_rule_model import (
    CATEGORICAL_VALUE_CODES,
    HIGH,
    ICHIMOKU_RULE_EVIDENCE,
    LOW,
    MEAN_REVERSION_RULE_EVIDENCE,
    SUPPORT_RESISTANCE_RULE_EVIDENCE,
    is_categorical_evidence,
    is_context_timeframe_evidence,
    new_rule,
    rule_operator_options,
    rule_value_options,
)
from .rule_strategy_builder import (
    EVIDENCE_LABELS,
    EvidenceComboBox,
    OPERATOR_LABELS,
    SR_TIMEFRAME_OPTIONS,
)


def _humanize(value) -> str:
    return str(value).replace("_", " ").title()


def _combo(options, current):
    box = QComboBox()
    for native, label in options:
        box.addItem(label, native)
    index = box.findData(current)
    box.setCurrentIndex(max(index, 0))
    return box


def _number(value: float = 0.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(-1_000_000_000.0, 1_000_000_000.0)
    box.setDecimals(6)
    box.setValue(float(value))
    box.setMinimumWidth(110)
    return box


def _categorical_from_code(indicator: str, code: float):
    mapping = CATEGORICAL_VALUE_CODES.get(indicator, {})
    for value, numeric in mapping.items():
        if float(numeric) == float(code):
            return value
    return None


def _decompile_native_rule(native: dict) -> dict:
    """Recover one editable positive condition while preserving unknown legacy rules."""
    indicator = str(native.get("indicator", "DIRECTIONAL_DI_RATIO")).upper()

    metadata_operator = native.get("_ladder_operator", native.get("_builder_operator"))
    metadata_value = native.get("_ladder_value", native.get("_builder_value"))
    metadata_value2 = native.get("_ladder_value2", native.get("_builder_value2"))
    if metadata_operator:
        result = {
            "evidence": indicator,
            "operator": str(metadata_operator).upper(),
            "value": metadata_value,
            "value2": metadata_value2,
            "sr_timeframe_minutes": native.get(
                "_builder_sr_timeframe_minutes",
                native.get("_ladder_sr_timeframe_minutes"),
            ),
        }
        return result

    condition = str(native.get("condition", "INSIDE")).upper()
    minimum = float(native.get("minimum", 0.0))
    maximum = float(native.get("maximum", 0.0))

    if is_categorical_evidence(indicator):
        if minimum == maximum:
            value = _categorical_from_code(indicator, minimum)
            if value is not None:
                return {
                    "evidence": indicator,
                    "operator": "IS" if condition == "INSIDE" else "IS_NOT",
                    "value": value,
                    "value2": None,
                    "sr_timeframe_minutes": native.get("_builder_sr_timeframe_minutes"),
                }
        default = new_rule(kind="REQUIRED", evidence=indicator)
        return {
            "evidence": indicator,
            "operator": default["operator"],
            "value": default["value"],
            "value2": default["value2"],
            "sr_timeframe_minutes": native.get("_builder_sr_timeframe_minutes"),
        }

    if condition == "INSIDE":
        if minimum <= LOW:
            operator, value, value2 = "LTE", maximum, 0.0
        elif maximum >= HIGH:
            operator, value, value2 = "GTE", minimum, 0.0
        else:
            operator, value, value2 = "BETWEEN", minimum, maximum
    else:
        if minimum <= LOW:
            operator, value, value2 = "GT", maximum, 0.0
        elif maximum >= HIGH:
            operator, value, value2 = "LT", minimum, 0.0
        else:
            operator, value, value2 = "OUTSIDE", minimum, maximum

    return {
        "evidence": indicator,
        "operator": operator,
        "value": value,
        "value2": value2,
        "sr_timeframe_minutes": native.get("_builder_sr_timeframe_minutes"),
    }


def _compile_positive_rule(state: dict, base: dict | None = None) -> dict:
    """Compile the visible positive condition to the native ladder matcher."""
    indicator = str(state["evidence"]).upper()
    operator = str(state["operator"]).upper()

    if is_categorical_evidence(indicator):
        code = float(CATEGORICAL_VALUE_CODES[indicator][str(state["value"]).upper()])
        minimum = maximum = code
        condition = "INSIDE" if operator == "IS" else "OUTSIDE"
        value = str(state["value"]).upper()
        value2 = None
    else:
        value = float(state["value"])
        value2 = float(state.get("value2") or 0.0)
        if operator == "GT":
            minimum, maximum, condition = LOW, value, "OUTSIDE"
        elif operator == "GTE":
            minimum, maximum, condition = value, HIGH, "INSIDE"
        elif operator == "LT":
            minimum, maximum, condition = value, HIGH, "OUTSIDE"
        elif operator == "LTE":
            minimum, maximum, condition = LOW, value, "INSIDE"
        elif operator == "BETWEEN":
            minimum, maximum, condition = value, value2, "INSIDE"
        elif operator == "OUTSIDE":
            minimum, maximum, condition = value, value2, "OUTSIDE"
        else:
            raise ValueError(f"Unsupported ladder rule operator: {operator}")

    if minimum > maximum:
        raise ValueError("Ladder rule minimum cannot exceed maximum")

    native = deepcopy(base) if isinstance(base, dict) else {}
    native.update(
        {
            "indicator": indicator,
            "condition": condition,
            "minimum": float(minimum),
            "maximum": float(maximum),
            "_ladder_operator": operator,
            "_ladder_value": value,
            "_ladder_value2": value2,
        }
    )
    if is_context_timeframe_evidence(indicator):
        timeframe = state.get("sr_timeframe_minutes")
        native["_builder_sr_timeframe_minutes"] = (
            None if timeframe is None else int(timeframe)
        )
        native["_ladder_sr_timeframe_minutes"] = (
            None if timeframe is None else int(timeframe)
        )
    else:
        native.pop("_builder_sr_timeframe_minutes", None)
        native.pop("_ladder_sr_timeframe_minutes", None)
    # Positive ladder rules must never inherit REQUIRED missing-evidence reject
    # semantics from a copied Strategy Builder rule.
    native.pop("_builder_kind", None)
    native.pop("action", None)
    return native


class LadderConditionCard(QFrame):
    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, native_rule: dict | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("ladderConditionCard")
        self.setStyleSheet(
            "QFrame#ladderConditionCard {"
            "background:#ffffff; border:1px solid #e4eaf0; border-radius:5px;"
            "}"
        )
        self._base = deepcopy(native_rule) if isinstance(native_rule, dict) else None
        self._dirty = native_rule is None
        if native_rule is None:
            seed = new_rule(kind="REQUIRED", evidence="DIRECTIONAL_DI_RATIO")
            self._state = {
                "evidence": seed["evidence"],
                "operator": seed["operator"],
                "value": seed["value"],
                "value2": seed["value2"],
                "sr_timeframe_minutes": seed.get("sr_timeframe_minutes", 0),
            }
        else:
            self._state = _decompile_native_rule(native_rule)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 7, 8, 7)
        outer.setSpacing(5)

        top = QHBoxLayout()
        self.evidence = EvidenceComboBox(self._state["evidence"])
        self.evidence.setMinimumWidth(230)
        self.remove_button = QPushButton("×")
        self.remove_button.setFixedWidth(28)
        self.remove_button.setToolTip("Remove this ladder condition")
        top.addWidget(self.evidence, 1)
        top.addWidget(self.remove_button)
        outer.addLayout(top)

        self.controls = QHBoxLayout()
        self.controls.setSpacing(6)
        self.timeframe = _combo(
            SR_TIMEFRAME_OPTIONS, self._state.get("sr_timeframe_minutes")
        )
        self.timeframe.setMinimumWidth(105)
        self.controls.addWidget(self.timeframe, 1)
        self.operator = None
        self.value = None
        self.upper = None
        self._build_value_controls(
            self._state["evidence"],
            self._state["operator"],
            self._state["value"],
            self._state.get("value2"),
        )
        self.controls.addStretch(1)
        outer.addLayout(self.controls)

        self.evidence.currentIndexChanged.connect(self._evidence_changed)
        self.timeframe.currentIndexChanged.connect(self._mark_changed)
        self.remove_button.clicked.connect(
            lambda _checked=False: self.remove_requested.emit(self)
        )
        self._refresh_timeframe()
        self._refresh_upper()
        self._dirty = native_rule is None

    def _operator_widget(self, evidence: str, current: str):
        options = rule_operator_options(evidence)
        selected = current if current in options else options[0]
        return _combo([(item, OPERATOR_LABELS[item]) for item in options], selected)

    def _value_widget(self, evidence: str, current):
        if is_categorical_evidence(evidence):
            values = rule_value_options(evidence)
            selected = str(current).upper() if current is not None else values[0]
            return _combo([(item, _humanize(item)) for item in values], selected)
        return _number(float(current or 0.0))

    def _upper_widget(self, evidence: str, current):
        if is_categorical_evidence(evidence):
            label = QLabel("—")
            label.setEnabled(False)
            return label
        return _number(float(current or 0.0))

    def _connect_editor(self, widget):
        if isinstance(widget, QDoubleSpinBox):
            widget.valueChanged.connect(self._mark_changed)
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(self._mark_changed)

    def _build_value_controls(self, evidence, operator, value, value2):
        self.operator = self._operator_widget(evidence, operator)
        self.operator.setMinimumWidth(90)
        self.value = self._value_widget(evidence, value)
        self.upper = self._upper_widget(evidence, value2)
        self.controls.addWidget(self.operator, 1)
        self.controls.addWidget(self.value, 2)
        self.controls.addWidget(self.upper, 2)
        self._connect_editor(self.operator)
        self._connect_editor(self.value)
        self._connect_editor(self.upper)
        self.operator.currentIndexChanged.connect(self._refresh_upper)

    def _replace_value_controls(self, evidence, operator, value, value2):
        old = (self.operator, self.value, self.upper)
        insert_at = 1
        for widget in old:
            self.controls.removeWidget(widget)
            widget.deleteLater()
        self.operator = self._operator_widget(evidence, operator)
        self.operator.setMinimumWidth(90)
        self.value = self._value_widget(evidence, value)
        self.upper = self._upper_widget(evidence, value2)
        for widget in (self.operator, self.value, self.upper):
            self.controls.insertWidget(insert_at, widget, 1 if widget is self.operator else 2)
            insert_at += 1
            self._connect_editor(widget)
        self.operator.currentIndexChanged.connect(self._refresh_upper)

    def _evidence_changed(self, _index):
        evidence = str(self.evidence.currentData())
        default = new_rule(kind="REQUIRED", evidence=evidence)
        self._replace_value_controls(
            evidence, default["operator"], default["value"], default["value2"]
        )
        if is_context_timeframe_evidence(evidence):
            if self.timeframe.currentData() is None:
                index = self.timeframe.findData(0)
                if index >= 0:
                    self.timeframe.setCurrentIndex(index)
        self._refresh_timeframe()
        self._refresh_upper()
        self._mark_changed()

    def _refresh_timeframe(self):
        self.timeframe.setVisible(
            is_context_timeframe_evidence(str(self.evidence.currentData()))
        )

    def _refresh_upper(self, *_args):
        if self.upper is None:
            return
        visible = (
            not is_categorical_evidence(str(self.evidence.currentData()))
            and str(self.operator.currentData()) in {"BETWEEN", "OUTSIDE"}
        )
        self.upper.setVisible(visible)
        self.upper.setEnabled(visible)

    def _mark_changed(self, *_args):
        self._dirty = True
        self._refresh_timeframe()
        self._refresh_upper()
        self.changed.emit()

    def state(self) -> dict:
        evidence = str(self.evidence.currentData())
        value = (
            self.value.currentData()
            if isinstance(self.value, QComboBox)
            else self.value.value()
        )
        value2 = self.upper.value() if isinstance(self.upper, QDoubleSpinBox) else None
        return {
            "evidence": evidence,
            "operator": str(self.operator.currentData()),
            "value": value,
            "value2": value2,
            "sr_timeframe_minutes": (
                self.timeframe.currentData()
                if is_context_timeframe_evidence(evidence)
                else None
            ),
        }

    def native_rule(self) -> dict:
        if self._base is not None and not self._dirty:
            return deepcopy(self._base)
        return _compile_positive_rule(self.state(), self._base)


class LadderLayerPanel(QWidget):
    changed = Signal()

    def __init__(self, layer: dict, parent=None):
        super().__init__(parent)
        self._base = deepcopy(layer)
        self.conditions: list[LadderConditionCard] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(8)

        geometry = QGroupBox("Layer Setup")
        form = QFormLayout(geometry)
        self.enabled = QCheckBox("Enable this ladder layer")
        self.enabled.setChecked(bool(layer.get("enabled", True)))
        self.name = QLineEdit(str(layer.get("name", "S1")))
        self.entry = _number(float(layer.get("entry_level", -1.0)))
        self.target = _number(float(layer.get("target_level", -2.0)))
        self.stop = _number(float(layer.get("stop_level", 1.0)))
        for box in (self.entry, self.target, self.stop):
            box.setSuffix(" levels")
        self.match_mode = QComboBox()
        self.match_mode.addItem("ALL conditions must pass (AND)", "ALL")
        self.match_mode.addItem("ANY condition may pass (OR)", "ANY")
        match_index = self.match_mode.findData(
            str(layer.get("filter_match_mode", "ALL")).upper()
        )
        self.match_mode.setCurrentIndex(max(match_index, 0))
        form.addRow(self.enabled)
        form.addRow("Layer Name", self.name)
        form.addRow("Entry Level", self.entry)
        form.addRow("Target Level", self.target)
        form.addRow("Stop Level", self.stop)
        form.addRow("Condition Match", self.match_mode)
        outer.addWidget(geometry)

        rules = QGroupBox("Entry Rule Workspace")
        rules_outer = QVBoxLayout(rules)
        self.logic = QLabel()
        self.logic.setWordWrap(True)
        self.logic.setStyleSheet(
            "color:#52606d; background:#f7f9fb; padding:6px; border-radius:4px"
        )
        rules_outer.addWidget(self.logic)

        self.condition_host = QWidget()
        self.condition_layout = QVBoxLayout(self.condition_host)
        self.condition_layout.setContentsMargins(0, 0, 0, 0)
        self.condition_layout.setSpacing(6)
        rules_outer.addWidget(self.condition_host)

        self.empty = QLabel(
            "No ladder filters. This layer enters mechanically when its level is reached."
        )
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color:#7b8794; padding:18px")
        self.condition_layout.addWidget(self.empty)

        actions = QHBoxLayout()
        self.add_button = QPushButton("+ Add Entry Condition")
        actions.addWidget(self.add_button)
        actions.addStretch()
        rules_outer.addLayout(actions)
        outer.addWidget(rules)
        outer.addStretch()

        for native in layer.get("entry_rules", ()) or ():
            if isinstance(native, dict):
                self._add_condition(native, emit=False)

        for widget, signal in (
            (self.enabled, self.enabled.toggled),
            (self.name, self.name.textChanged),
            (self.entry, self.entry.valueChanged),
            (self.target, self.target.valueChanged),
            (self.stop, self.stop.valueChanged),
            (self.match_mode, self.match_mode.currentIndexChanged),
        ):
            signal.connect(self._changed)
        self.match_mode.currentIndexChanged.connect(self._refresh_logic)
        self.add_button.clicked.connect(self.add_condition)
        self._refresh_logic()
        self._refresh_empty()

    def _refresh_logic(self, *_args):
        if self.match_mode.currentData() == "ANY":
            text = "Positive ladder-entry filters: ANY condition below may qualify this layer (OR). Missing evidence does not qualify."
        else:
            text = "Positive ladder-entry filters: ALL conditions below must qualify this layer (AND). Missing evidence fails that condition."
        self.logic.setText(text)

    def _refresh_empty(self):
        self.empty.setVisible(not self.conditions)

    def _changed(self, *_args):
        self._refresh_logic()
        self.changed.emit()

    def _add_condition(self, native=None, *, emit=True):
        card = LadderConditionCard(native)
        card.changed.connect(self.changed)
        card.remove_requested.connect(self.remove_condition)
        self.conditions.append(card)
        self.condition_layout.insertWidget(
            max(0, self.condition_layout.count() - 1), card
        )
        self._refresh_empty()
        if emit:
            self.changed.emit()
        return card

    def add_condition(self):
        return self._add_condition(None)

    def remove_condition(self, card):
        if card not in self.conditions:
            return
        self.conditions.remove(card)
        self.condition_layout.removeWidget(card)
        card.deleteLater()
        self._refresh_empty()
        self.changed.emit()

    def layer(self) -> dict:
        result = deepcopy(self._base)
        result.update(
            {
                "name": self.name.text().strip() or "Layer",
                "enabled": self.enabled.isChecked(),
                "entry_level": float(self.entry.value()),
                "target_level": float(self.target.value()),
                "stop_level": float(self.stop.value()),
                "filter_match_mode": str(self.match_mode.currentData()),
                "entry_rules": [card.native_rule() for card in self.conditions],
            }
        )
        return result


class LadderRuleWorkspace(QWidget):
    changed = Signal()

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.account = window.execution_form.widgets
        self._syncing = False
        self.panels: list[LadderLayerPanel] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        intro = QLabel(
            "Configure S1/S2/S3/S4 without editing JSON. Each layer is evaluated only when its price level is first reached. "
            "These are positive ENTER filters for the opposite-side ladder trade; a failed layer is skipped while deeper layers remain eligible."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(
            "background:#eef5fb; padding:8px; border:1px solid #c8d9e8"
        )
        outer.addWidget(intro)

        global_box = QGroupBox("DI Ladder")
        global_form = QFormLayout(global_box)
        self.enabled = QCheckBox("Enable DI ladder / reversal-filter execution")
        self.level_size = QDoubleSpinBox()
        self.level_size.setRange(0.000001, 1_000_000.0)
        self.level_size.setDecimals(6)
        self.level_size.setSuffix(" R")
        global_form.addRow(self.enabled)
        global_form.addRow("Ladder Level Size", self.level_size)
        outer.addWidget(global_box)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(
            "color:#334e68; background:#f7f9fb; padding:8px; border:1px solid #d9e2ec"
        )
        outer.addWidget(self.summary)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self.enabled.toggled.connect(self._global_enabled_changed)
        self.level_size.valueChanged.connect(self._global_level_changed)
        self.account["di_ladder_enabled"].toggled.connect(
            self._authoritative_enabled_changed
        )
        self.account["di_ladder_level_r"].valueChanged.connect(
            self._authoritative_level_changed
        )
        self.account["di_ladder_layers"].textChanged.connect(
            self._authoritative_layers_changed
        )
        self.load_from_authoritative()

    def _authoritative_enabled_changed(self, checked):
        if self._syncing:
            return
        self.enabled.blockSignals(True)
        self.enabled.setChecked(bool(checked))
        self.enabled.blockSignals(False)
        self._refresh_summary()

    def _authoritative_level_changed(self, value):
        if self._syncing:
            return
        self.level_size.blockSignals(True)
        self.level_size.setValue(float(value))
        self.level_size.blockSignals(False)
        self._refresh_summary()

    def _authoritative_layers_changed(self):
        if not self._syncing:
            self.load_from_authoritative()

    def _global_enabled_changed(self, checked):
        if self._syncing:
            return
        self._syncing = True
        try:
            self.account["di_ladder_enabled"].setChecked(bool(checked))
        finally:
            self._syncing = False
        self._refresh_summary()
        self.changed.emit()

    def _global_level_changed(self, value):
        if self._syncing:
            return
        self._syncing = True
        try:
            self.account["di_ladder_level_r"].setValue(float(value))
        finally:
            self._syncing = False
        self._refresh_summary()
        self.changed.emit()

    def _clear_tabs(self):
        while self.tabs.count():
            widget = self.tabs.widget(0)
            self.tabs.removeTab(0)
            widget.deleteLater()
        self.panels = []

    def load_from_authoritative(self):
        current = self.tabs.currentIndex()
        self._syncing = True
        try:
            self.enabled.setChecked(
                bool(self.account["di_ladder_enabled"].isChecked())
            )
            self.level_size.setValue(
                float(self.account["di_ladder_level_r"].value())
            )
            try:
                layers = self.account["di_ladder_layers"].tuple_value()
            except (ValueError, TypeError):
                layers = ()
            self._clear_tabs()
            for number, layer in enumerate(layers, 1):
                if not isinstance(layer, dict):
                    continue
                panel = LadderLayerPanel(layer)
                panel.changed.connect(self._layers_changed)
                self.panels.append(panel)
                self.tabs.addTab(panel, str(layer.get("name") or f"S{number}"))
            if self.tabs.count():
                self.tabs.setCurrentIndex(
                    min(max(current, 0), self.tabs.count() - 1)
                )
        finally:
            self._syncing = False
        self._refresh_summary()

    def _layers_changed(self):
        if self._syncing:
            return
        layers = tuple(panel.layer() for panel in self.panels)
        self._syncing = True
        try:
            self.account["di_ladder_layers"].set_tuple(layers)
        finally:
            self._syncing = False
        for index, panel in enumerate(self.panels):
            self.tabs.setTabText(index, panel.name.text().strip() or f"S{index + 1}")
        self._refresh_summary()
        refresh = getattr(self.window, "_refresh_summary_from_widgets", None)
        if callable(refresh):
            refresh()
        self.changed.emit()

    def _refresh_summary(self):
        active = sum(panel.enabled.isChecked() for panel in self.panels)
        rules = sum(len(panel.conditions) for panel in self.panels)
        state = "Enabled" if self.enabled.isChecked() else "Disabled"
        self.summary.setText(
            f"{state} · {active}/{len(self.panels)} layers active · "
            f"{rules} ladder entry condition(s) · level size {self.level_size.value():g} R"
        )


def apply_ladder_rule_dependencies(config):
    """Turn on causal feature blocks needed by enabled ladder rules."""
    if not config.execution.di_ladder_enabled:
        return config

    rules = [
        rule
        for layer in config.execution.di_ladder_layers
        if isinstance(layer, dict) and bool(layer.get("enabled", True))
        for rule in (layer.get("entry_rules", ()) or ())
        if isinstance(rule, dict)
    ]
    indicators = {str(rule.get("indicator", "")).upper() for rule in rules}
    if not indicators:
        return config

    features = config.features
    strategy = config.strategy

    if indicators & MEAN_REVERSION_RULE_EVIDENCE:
        strategy = replace(strategy, enable_mean_reversion_analysis=True)
        features = replace(
            features,
            mean_reversion_track_atr_distance=True,
            mean_reversion_track_motion=True,
        )

    if indicators & ICHIMOKU_RULE_EVIDENCE:
        strategy_tf = int(config.data.strategy_timeframe_minutes)
        higher = any(
            str(rule.get("indicator", "")).upper() in ICHIMOKU_RULE_EVIDENCE
            and rule.get("_builder_sr_timeframe_minutes") not in (None, 0)
            and int(rule.get("_builder_sr_timeframe_minutes")) > strategy_tf
            for rule in rules
        )
        features = replace(
            features,
            ichimoku_enabled=True,
            ichimoku_include_higher_timeframes=(
                features.ichimoku_include_higher_timeframes or higher
            ),
        )

    if indicators & SUPPORT_RESISTANCE_RULE_EVIDENCE:
        features = replace(features, enable_support_resistance_analysis=True)

    if features == config.features and strategy == config.strategy:
        return config
    updated = replace(config, features=features, strategy=strategy)
    updated.validate()
    return updated
