"""Researcher-facing rule-based strategy builder.

Users choose where the strategy may trade and then express every entry-affecting
condition through scoped Entry/Veto rules. DI pressure and support/resistance are
causal research evidence, not separate hidden/global filters.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from crypto_strategy_lab.strategy_profiles import RULE_INDICATORS
from crypto_strategy_lab.strategy_rule_model import (
    DIRECTION_MODES,
    MARKET_PERMISSIONS,
    REGIMES,
    SIDES,
    decompile_rules,
    infer_direction_mode,
    infer_market_permissions,
    is_categorical_evidence,
    new_rule,
    normalize_rule,
    normalize_rules,
    rule_operator_options,
    rule_value_options,
)


EVIDENCE_LABELS = {
    "DI_SPREAD": "DI Spread",
    "DIRECTIONAL_DI": "Directional DI",
    "DIRECTIONAL_DI_RATIO": "Directional DI Ratio",
    "DI_PRESSURE_STATE": "DI Pressure State",
    "DI_SPREAD_CHANGE": "DI Spread Change",
    "DIRECTIONAL_DI_CHANGE": "Directional DI Change",
    "OPPOSING_DI_CHANGE": "Opposing DI Change",
    "ADX": "ADX",
    "ADX_CHANGE": "ADX Change (1 bar)",
    "ATR_PCT": "ATR % (decimal)",
    "EMA_50_DISTANCE_ATR": "Price − EMA 50 (ATR)",
    "EMA_100_DISTANCE_ATR": "Price − EMA 100 (ATR)",
    "EMA_200_DISTANCE_ATR": "Price − EMA 200 (ATR)",
    "EMA_STACK_STATE": "EMA Stack State (50 / 100 / 200)",
    "MACD_LINE": "MACD Line (12/26)",
    "MACD_SIGNAL": "MACD Signal (9)",
    "MACD_HISTOGRAM": "MACD Histogram",
    "MACD_HISTOGRAM_CHANGE": "MACD Histogram Change (1 bar)",
    "MACD_CROSS_STATE": "MACD Cross State",
    "MACD_ZERO_STATE": "MACD Zero State",
    "RSI": "RSI",
    "BB_WIDTH": "BB Width (decimal)",
    "CLOSE_LOCATION": "Close Location",
    "MOMENTUM": "Momentum Return",
    "VWAP_DISTANCE": "VWAP Distance (ATR)",
    "MR_TRADE_STRETCH_ATR": "MR — Trade-Direction Stretch (ATR)",
    "MR_DISTANCE_ATR": "MR — Price − Mean (ATR)",
    "MR_MOTION": "MR — Motion",
    "MR_BB_ZSCORE": "MR — BB Z-Score",
    "MR_BB_LOCATION": "MR — BB Location",
    "MR_SIGNAL": "MR — Signal",
    "MR_TRADE_ALIGNMENT": "MR — Trade Alignment",
    "MR_STRENGTH": "MR — Strength",
    "MR_STATE": "MR — State",
    "MR_DISTANCE_CHANGE_ATR": "MR — Distance Change (ATR, 1 bar)",
    "SR_NEAR_SUPPORT": "S/R — Near Support",
    "SR_NEAR_RESISTANCE": "S/R — Near Resistance",
    "SR_INSIDE_SUPPORT_ZONE": "S/R — Inside Support Zone",
    "SR_INSIDE_RESISTANCE_ZONE": "S/R — Inside Resistance Zone",
    "SR_SUPPORT_STATE": "S/R — Support State",
    "SR_RESISTANCE_STATE": "S/R — Resistance State",
    "SR_SUPPORT_HELD": "S/R — Support Held",
    "SR_RESISTANCE_HELD": "S/R — Resistance Held",
    "SR_TRADE_LOCATION_RATING": "S/R — Trade Location Rating",
    "SR_ROOM_IN_DIRECTION_ATR": "S/R — Room In Direction (ATR)",
    "SR_SUPPORT_DISTANCE_ATR": "S/R — Support Distance (ATR)",
    "SR_RESISTANCE_DISTANCE_ATR": "S/R — Resistance Distance (ATR)",
    "SR_SUPPORT_REJECTION_ATR": "S/R — Support Rejection (ATR)",
    "SR_RESISTANCE_REJECTION_ATR": "S/R — Resistance Rejection (ATR)",
    "SR_SUPPORT_TEST_COUNT": "S/R — Support Test Count",
    "SR_RESISTANCE_TEST_COUNT": "S/R — Resistance Test Count",
    "SR_BARS_SINCE_SUPPORT_TEST": "S/R — Bars Since Support Test",
    "SR_BARS_SINCE_RESISTANCE_TEST": "S/R — Bars Since Resistance Test",
    "OI_CHANGE_PCT_5M": "OI Change 5m (decimal)",
    "OI_CHANGE_PCT_1H": "OI Change 1h (decimal)",
    "OI_CHANGE_PCT_24H": "OI Change 24h (decimal)",
    "OI_ZSCORE_7D": "OI Z-Score (7d)",
    "PRICE_CHANGE_PCT_1H": "Price Change 1h (decimal)",
    "PRICE_OI_STATE": "Price / OI State (Strategy Bar)",
    "OI_VS_PRICE_STATE_1H": "Price / OI State (1h)",
    "TOP_TRADER_ACCOUNT_BIAS": "Top Trader Account Bias (ratio − 1)",
    "TOP_TRADER_POSITION_BIAS": "Top Trader Position Bias (ratio − 1)",
    "GLOBAL_LONG_SHORT_ACCOUNT_BIAS": "Global Long/Short Account Bias (ratio − 1)",
    "TAKER_LONG_SHORT_VOLUME_BIAS": "Taker Long/Short Volume Bias (ratio − 1)",
    "FUNDING_RATE_BPS": "Funding Rate (bps)",
    "FUNDING_BIAS": "Funding Bias",
    "FUNDING_24H_SUM_BPS": "Funding 24h Sum (bps)",
    "FUNDING_CHANGE_BPS": "Funding Change (bps)",
    "FUNDING_3_EVENT_MEAN_BPS": "Funding 3-Event Mean (bps)",
    "FUNDING_ZSCORE_7D": "Funding Z-Score (7d)",
    "FUNDING_EXTREME_POSITIVE": "Funding Extreme Positive",
    "FUNDING_EXTREME_NEGATIVE": "Funding Extreme Negative",
    "MARK_INDEX_BASIS_BPS": "Mark − Index Basis (bps)",
    "MARK_INDEX_BASIS_STATE": "Mark / Index Basis State",
    "MARK_INDEX_BASIS_ZSCORE_7D": "Mark / Index Basis Z-Score (7d)",
    "TRADE_MARK_BASIS_BPS": "Trade − Mark Basis (bps)",
    "TRADE_INDEX_BASIS_BPS": "Trade − Index Basis (bps)",
    "PREMIUM_INDEX_ZSCORE_7D": "Premium Index Z-Score (7d)",
    "TAKER_BUY_SELL_RATIO": "Taker Buy / Sell Ratio",
    "TAKER_DELTA_PCT": "Taker Delta (source interval, decimal)",
    "TAKER_DELTA_PCT_15M": "Taker Delta 15m (decimal)",
    "TAKER_DELTA_PCT_1H": "Taker Delta 1h (decimal)",
    "TAKER_FLOW_PERSISTENCE": "Taker Flow Persistence (0–1)",
}
EVIDENCE_GROUPS = (
    (
        "Directional / DI",
        (
            "DIRECTIONAL_DI",
            "DIRECTIONAL_DI_RATIO",
            "DI_SPREAD",
            "DI_PRESSURE_STATE",
            "DIRECTIONAL_DI_CHANGE",
            "OPPOSING_DI_CHANGE",
            "DI_SPREAD_CHANGE",
        ),
    ),
    (
        "Trend & Volatility",
        (
            "ADX", "ADX_CHANGE", "ATR_PCT", "BB_WIDTH",
            "EMA_50_DISTANCE_ATR", "EMA_100_DISTANCE_ATR", "EMA_200_DISTANCE_ATR",
            "EMA_STACK_STATE",
        ),
    ),
    (
        "Momentum & Price",
        (
            "RSI", "MOMENTUM", "CLOSE_LOCATION", "VWAP_DISTANCE",
            "MACD_LINE", "MACD_SIGNAL", "MACD_HISTOGRAM",
            "MACD_HISTOGRAM_CHANGE", "MACD_CROSS_STATE", "MACD_ZERO_STATE",
        ),
    ),
    (
        "Mean Reversion",
        (
            "MR_TRADE_STRETCH_ATR",
            "MR_DISTANCE_ATR",
            "MR_MOTION",
            "MR_BB_ZSCORE",
            "MR_BB_LOCATION",
            "MR_SIGNAL",
            "MR_TRADE_ALIGNMENT",
            "MR_STRENGTH",
            "MR_STATE",
            "MR_DISTANCE_CHANGE_ATR",
        ),
    ),
    (
        "Futures — Open Interest & Positioning",
        (
            "PRICE_OI_STATE",
            "OI_VS_PRICE_STATE_1H",
            "OI_CHANGE_PCT_5M",
            "OI_CHANGE_PCT_1H",
            "OI_CHANGE_PCT_24H",
            "OI_ZSCORE_7D",
            "PRICE_CHANGE_PCT_1H",
            "TOP_TRADER_ACCOUNT_BIAS",
            "TOP_TRADER_POSITION_BIAS",
            "GLOBAL_LONG_SHORT_ACCOUNT_BIAS",
            "TAKER_LONG_SHORT_VOLUME_BIAS",
        ),
    ),
    (
        "Futures — Funding",
        (
            "FUNDING_BIAS",
            "FUNDING_RATE_BPS",
            "FUNDING_24H_SUM_BPS",
            "FUNDING_CHANGE_BPS",
            "FUNDING_3_EVENT_MEAN_BPS",
            "FUNDING_ZSCORE_7D",
            "FUNDING_EXTREME_POSITIVE",
            "FUNDING_EXTREME_NEGATIVE",
        ),
    ),
    (
        "Futures — Basis / Premium",
        (
            "MARK_INDEX_BASIS_STATE",
            "MARK_INDEX_BASIS_BPS",
            "MARK_INDEX_BASIS_ZSCORE_7D",
            "TRADE_MARK_BASIS_BPS",
            "TRADE_INDEX_BASIS_BPS",
            "PREMIUM_INDEX_ZSCORE_7D",
        ),
    ),
    (
        "Futures — Taker Flow",
        (
            "TAKER_BUY_SELL_RATIO",
            "TAKER_DELTA_PCT",
            "TAKER_DELTA_PCT_15M",
            "TAKER_DELTA_PCT_1H",
            "TAKER_FLOW_PERSISTENCE",
        ),
    ),
    (
        "Support & Resistance",
        (
            "SR_TRADE_LOCATION_RATING",
            "SR_ROOM_IN_DIRECTION_ATR",
            "SR_NEAR_SUPPORT",
            "SR_NEAR_RESISTANCE",
            "SR_INSIDE_SUPPORT_ZONE",
            "SR_INSIDE_RESISTANCE_ZONE",
        ),
    ),
    (
        "Support & Resistance — Advanced",
        (
            "SR_SUPPORT_STATE",
            "SR_RESISTANCE_STATE",
            "SR_SUPPORT_HELD",
            "SR_RESISTANCE_HELD",
            "SR_SUPPORT_DISTANCE_ATR",
            "SR_RESISTANCE_DISTANCE_ATR",
            "SR_SUPPORT_REJECTION_ATR",
            "SR_RESISTANCE_REJECTION_ATR",
            "SR_SUPPORT_TEST_COUNT",
            "SR_RESISTANCE_TEST_COUNT",
            "SR_BARS_SINCE_SUPPORT_TEST",
            "SR_BARS_SINCE_RESISTANCE_TEST",
        ),
    ),
)

# Category-first menu structure. Leaves are evidence IDs; nested tuples are
# (submenu label, children). Keeping EVIDENCE_GROUPS above preserves the flat
# research grouping used elsewhere while the popup remains compact.
EVIDENCE_MENU_TREE = (
    (
        "Directional / DI",
        (
            "DIRECTIONAL_DI",
            "DIRECTIONAL_DI_RATIO",
            "DI_SPREAD",
            "DI_PRESSURE_STATE",
            "DIRECTIONAL_DI_CHANGE",
            "OPPOSING_DI_CHANGE",
            "DI_SPREAD_CHANGE",
        ),
    ),
    (
        "Trend & Volatility",
        (
            "ADX", "ADX_CHANGE", "ATR_PCT", "BB_WIDTH",
            "EMA_50_DISTANCE_ATR", "EMA_100_DISTANCE_ATR", "EMA_200_DISTANCE_ATR",
            "EMA_STACK_STATE",
        ),
    ),
    (
        "Momentum & Price",
        (
            "RSI", "MOMENTUM", "CLOSE_LOCATION", "VWAP_DISTANCE",
            (
                "MACD",
                (
                    "MACD_LINE", "MACD_SIGNAL", "MACD_HISTOGRAM",
                    "MACD_HISTOGRAM_CHANGE", "MACD_CROSS_STATE", "MACD_ZERO_STATE",
                ),
            ),
        ),
    ),
    (
        "Mean Reversion",
        (
            (
                "Entry Location",
                ("MR_TRADE_STRETCH_ATR", "MR_DISTANCE_ATR", "MR_MOTION"),
            ),
            (
                "Confirmation",
                ("MR_BB_ZSCORE", "MR_BB_LOCATION", "MR_SIGNAL", "MR_TRADE_ALIGNMENT"),
            ),
            (
                "Advanced",
                ("MR_STRENGTH", "MR_STATE", "MR_DISTANCE_CHANGE_ATR"),
            ),
        ),
    ),
    (
        "Futures",
        (
            (
                "Open Interest & Positioning",
                (
                    "PRICE_OI_STATE",
                    "OI_VS_PRICE_STATE_1H",
                    "OI_CHANGE_PCT_5M",
                    "OI_CHANGE_PCT_1H",
                    "OI_CHANGE_PCT_24H",
                    "OI_ZSCORE_7D",
                    "PRICE_CHANGE_PCT_1H",
                    "TOP_TRADER_ACCOUNT_BIAS",
                    "TOP_TRADER_POSITION_BIAS",
                    "GLOBAL_LONG_SHORT_ACCOUNT_BIAS",
                    "TAKER_LONG_SHORT_VOLUME_BIAS",
                ),
            ),
            (
                "Funding",
                (
                    "FUNDING_BIAS",
                    "FUNDING_RATE_BPS",
                    "FUNDING_24H_SUM_BPS",
                    "FUNDING_CHANGE_BPS",
                    "FUNDING_3_EVENT_MEAN_BPS",
                    "FUNDING_ZSCORE_7D",
                    "FUNDING_EXTREME_POSITIVE",
                    "FUNDING_EXTREME_NEGATIVE",
                ),
            ),
            (
                "Basis / Premium",
                (
                    "MARK_INDEX_BASIS_STATE",
                    "MARK_INDEX_BASIS_BPS",
                    "MARK_INDEX_BASIS_ZSCORE_7D",
                    "TRADE_MARK_BASIS_BPS",
                    "TRADE_INDEX_BASIS_BPS",
                    "PREMIUM_INDEX_ZSCORE_7D",
                ),
            ),
            (
                "Taker Flow",
                (
                    "TAKER_BUY_SELL_RATIO",
                    "TAKER_DELTA_PCT",
                    "TAKER_DELTA_PCT_15M",
                    "TAKER_DELTA_PCT_1H",
                    "TAKER_FLOW_PERSISTENCE",
                ),
            ),
        ),
    ),
    (
        "Support & Resistance",
        (
            "SR_TRADE_LOCATION_RATING",
            "SR_ROOM_IN_DIRECTION_ATR",
            "SR_NEAR_SUPPORT",
            "SR_NEAR_RESISTANCE",
            "SR_INSIDE_SUPPORT_ZONE",
            "SR_INSIDE_RESISTANCE_ZONE",
            (
                "Advanced S/R",
                (
                    "SR_SUPPORT_STATE",
                    "SR_RESISTANCE_STATE",
                    "SR_SUPPORT_HELD",
                    "SR_RESISTANCE_HELD",
                    "SR_SUPPORT_DISTANCE_ATR",
                    "SR_RESISTANCE_DISTANCE_ATR",
                    "SR_SUPPORT_REJECTION_ATR",
                    "SR_RESISTANCE_REJECTION_ATR",
                    "SR_SUPPORT_TEST_COUNT",
                    "SR_RESISTANCE_TEST_COUNT",
                    "SR_BARS_SINCE_SUPPORT_TEST",
                    "SR_BARS_SINCE_RESISTANCE_TEST",
                ),
            ),
        ),
    ),
)

OPERATOR_LABELS = {
    "GT": ">",
    "GTE": "≥",
    "LT": "<",
    "LTE": "≤",
    "BETWEEN": "Between",
    "OUTSIDE": "Outside range",
    "IS": "Is",
    "IS_NOT": "Is Not",
}
DIRECTION_LABELS = {
    "DI": "DI Direction",
    "DMI_TREND": "DMI Trend — Baseline",
    "MACD_PULLBACK": "MACD Pullback — 12/26/9",
}


def _humanize(value: str) -> str:
    return str(value).replace("_", " ").title()


def _evidence_menu_paths() -> dict[str, tuple[str, ...]]:
    """Return searchable category paths for every evidence leaf in the menu tree."""
    result: dict[str, tuple[str, ...]] = {}

    def visit(items, path):
        for item in items:
            if isinstance(item, str):
                result[item] = path
            else:
                label, children = item
                visit(children, (*path, label))

    for label, children in EVIDENCE_MENU_TREE:
        visit(children, (label,))
    return result


class EvidenceComboBox(QComboBox):
    """Evidence selector with compact categories plus global search."""

    def __init__(self, current: str | None = None, parent=None):
        super().__init__(parent)
        for evidence in RULE_INDICATORS:
            self.addItem(EVIDENCE_LABELS.get(evidence, evidence), evidence)
        index = self.findData(current)
        self.setCurrentIndex(max(index, 0))
        self.setToolTip("Browse evidence by category or search by name")

    def showPopup(self) -> None:
        menu = QMenu(self)
        menu.setMinimumWidth(max(self.width(), 360))

        search = QLineEdit(menu)
        search.setPlaceholderText("Search evidence…")
        search_action = QWidgetAction(menu)
        search_action.setDefaultWidget(search)
        menu.addAction(search_action)

        current = self.currentData()
        paths = _evidence_menu_paths()

        search_section = menu.addSection("Search Results")
        search_section.setVisible(False)
        search_actions = []
        for evidence in RULE_INDICATORS:
            label = EVIDENCE_LABELS.get(evidence, evidence)
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(evidence == current)
            action.setVisible(False)
            action.triggered.connect(
                lambda _checked=False, value=evidence: self._select_evidence(value)
            )
            path = paths.get(evidence, ("Other",))
            search_text = (
                f"{' '.join(path)} {label} {evidence.replace('_', ' ')}".casefold()
            )
            search_actions.append((action, search_text))

        no_matches = menu.addAction("No matching evidence")
        no_matches.setEnabled(False)
        no_matches.setVisible(False)

        category_separator = menu.addSeparator()
        category_actions = []
        tree_ids = set(paths)

        def add_items(parent_menu, items):
            for item in items:
                if isinstance(item, str):
                    if item not in RULE_INDICATORS:
                        continue
                    label = EVIDENCE_LABELS.get(item, item)
                    action = parent_menu.addAction(label)
                    action.setCheckable(True)
                    action.setChecked(item == current)
                    action.triggered.connect(
                        lambda _checked=False, value=item: self._select_evidence(value)
                    )
                else:
                    label, children = item
                    submenu = parent_menu.addMenu(label)
                    add_items(submenu, children)

        for label, children in EVIDENCE_MENU_TREE:
            submenu = menu.addMenu(label)
            add_items(submenu, children)
            category_actions.append(submenu.menuAction())

        uncategorized = tuple(
            evidence for evidence in RULE_INDICATORS if evidence not in tree_ids
        )
        if uncategorized:
            submenu = menu.addMenu("Other")
            add_items(submenu, uncategorized)
            category_actions.append(submenu.menuAction())

        def apply_filter(text: str) -> None:
            needle = text.strip().casefold()
            searching = bool(needle)
            any_match = False
            for action, search_text in search_actions:
                visible = searching and needle in search_text
                action.setVisible(visible)
                any_match = any_match or visible
            search_section.setVisible(searching and any_match)
            no_matches.setVisible(searching and not any_match)
            category_separator.setVisible(not searching)
            for action in category_actions:
                action.setVisible(not searching)

        search.textChanged.connect(apply_filter)
        search.setFocus()
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _select_evidence(self, evidence: str) -> None:
        index = self.findData(evidence)
        if index >= 0:
            self.setCurrentIndex(index)


class RuleTable(QWidget):
    """Card-based scoped condition-group editor.

    Conditions inside one group are ANDed. Groups are independent alternatives:
    any Entry group may qualify, while any Veto/Flip group may trigger its action.
    Market and side belong to the group header rather than being repeated on every
    condition. New groups and new conditions are inserted at the top so the latest
    edit stays in view.
    """

    changed = Signal()
    COLUMNS = (
        "group", "evidence", "operator", "value", "value2", "regime", "side"
    )

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._groups: dict[str, dict] = {}
        self._rows: list[dict] = []
        self._selected_row: int | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setMinimumHeight(190)

        self.cards_host = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_host)
        self.cards_layout.setContentsMargins(2, 2, 2, 2)
        self.cards_layout.setSpacing(8)
        self.scroll.setWidget(self.cards_host)
        outer.addWidget(self.scroll)

    @staticmethod
    def _combo(options, current):
        box = QComboBox()
        for native, label in options:
            box.addItem(label, native)
        index = box.findData(current)
        box.setCurrentIndex(max(index, 0))
        return box

    @staticmethod
    def _number(value: float):
        box = QDoubleSpinBox()
        box.setRange(-1_000_000_000.0, 1_000_000_000.0)
        box.setDecimals(6)
        box.setValue(float(value))
        box.setMinimumWidth(105)
        return box

    def _operator(self, evidence: str, current: str):
        options = rule_operator_options(evidence)
        selected = current if current in options else options[0]
        return self._combo(
            [(item, OPERATOR_LABELS[item]) for item in options], selected
        )

    def _value(self, evidence: str, current):
        if is_categorical_evidence(evidence):
            values = rule_value_options(evidence)
            selected = str(current).upper() if current is not None else values[0]
            return self._combo([(item, _humanize(item)) for item in values], selected)
        return self._number(float(current))

    def _upper(self, evidence: str, current):
        if is_categorical_evidence(evidence):
            label = QLabel("—")
            label.setEnabled(False)
            return label
        return self._number(float(current))

    def _connect_control(self, widget, group_id: str) -> None:
        if isinstance(widget, QDoubleSpinBox):
            widget.valueChanged.connect(
                lambda *_args, gid=group_id: self._notify_changed(gid)
            )
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(
                lambda *_args, gid=group_id: self._notify_changed(gid)
            )

    def _clear_cards(self) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._groups = {}
        self._rows = []
        self._selected_row = None

    def _make_condition_row(self, rule: dict, group_id: str) -> dict:
        wrapper = QWidget()
        row_layout = QHBoxLayout(wrapper)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        evidence = EvidenceComboBox(rule["evidence"])
        evidence.setMinimumWidth(190)
        operator = self._operator(rule["evidence"], rule["operator"])
        operator.setMinimumWidth(90)
        value = self._value(rule["evidence"], rule["value"])
        upper = self._upper(rule["evidence"], rule["value2"])
        remove = QPushButton("×")
        remove.setFixedWidth(28)
        remove.setToolTip("Remove this condition")

        row_layout.addWidget(evidence, 3)
        row_layout.addWidget(operator, 1)
        row_layout.addWidget(value, 2)
        row_layout.addWidget(upper, 2)
        row_layout.addWidget(remove)

        row_info = {
            "id": rule["id"],
            "group_id": group_id,
            "widget": wrapper,
            "layout": row_layout,
            "evidence": evidence,
            "operator": operator,
            "value": value,
            "upper": upper,
            "remove": remove,
        }
        self._rows.append(row_info)

        self._connect_control(operator, group_id)
        self._connect_control(value, group_id)
        if isinstance(upper, QDoubleSpinBox):
            self._connect_control(upper, group_id)

        evidence.currentIndexChanged.connect(
            lambda _index, rid=rule["id"]: self._evidence_changed(rid)
        )
        operator.currentIndexChanged.connect(
            lambda _index, rid=rule["id"]: self._refresh_upper_by_id(rid)
        )
        remove.clicked.connect(
            lambda _checked=False, rid=rule["id"]: self._remove_condition(rid)
        )
        self._refresh_upper_for_row(row_info)
        return row_info

    def _make_group_card(self, group_id: str, group_rules: list[dict]) -> QFrame:
        first = group_rules[0]
        card = QFrame()
        card.setObjectName("ruleGroupCard")
        card.setStyleSheet(
            "QFrame#ruleGroupCard {"
            "background:#ffffff; border:1px solid #d9e2ec; border-radius:7px;"
            "}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(7)

        header = QHBoxLayout()
        group_name = QLineEdit(first["group_name"])
        group_name.setPlaceholderText("Group name")
        group_name.setMinimumWidth(180)
        regime = self._combo(
            [
                ("ALL", "All Markets"),
                *((item, item.title()) for item in REGIMES),
            ],
            first["regime"],
        )
        side = self._combo(
            [
                ("ALL", "All Sides"),
                *((item, item.title()) for item in SIDES),
            ],
            first["side"],
        )
        delete_group = QPushButton("Delete group")
        delete_group.setToolTip("Remove this whole condition group")

        header.addWidget(group_name, 2)
        header.addStretch()
        header.addWidget(QLabel("Market"))
        header.addWidget(regime)
        header.addWidget(QLabel("Side"))
        header.addWidget(side)
        header.addWidget(delete_group)
        card_layout.addLayout(header)

        logic_text = {
            "REQUIRED": "ALL conditions below must match for this Entry group.",
            "VETO": "ALL conditions below must match for this Veto group.",
            "FLIP": "ALL conditions below must match for this Flip group.",
        }[self.kind]
        logic = QLabel(logic_text)
        logic.setStyleSheet("color:#52606d; font-size:11px")
        card_layout.addWidget(logic)

        conditions = QVBoxLayout()
        conditions.setSpacing(5)
        card_layout.addLayout(conditions)

        preview = QLabel()
        preview.setWordWrap(True)
        preview.setStyleSheet(
            "color:#334e68; background:#f7f9fb; padding:5px; border-radius:4px"
        )

        add_condition = QPushButton("+ Add condition")
        add_condition.setToolTip("Add a new condition at the top of this group")
        footer = QHBoxLayout()
        footer.addWidget(add_condition)
        footer.addStretch()

        self._groups[group_id] = {
            "id": group_id,
            "card": card,
            "name": group_name,
            "regime": regime,
            "side": side,
            "preview": preview,
        }

        for index, rule in enumerate(group_rules):
            if index:
                and_label = QLabel("AND")
                and_label.setAlignment(Qt.AlignCenter)
                and_label.setStyleSheet("color:#7b8794; font-weight:600")
                conditions.addWidget(and_label)
            row_info = self._make_condition_row(rule, group_id)
            conditions.addWidget(row_info["widget"])

        card_layout.addWidget(preview)
        card_layout.addLayout(footer)

        group_name.textChanged.connect(
            lambda _text, gid=group_id: self._notify_changed(gid)
        )
        regime.currentIndexChanged.connect(
            lambda _index, gid=group_id: self._notify_changed(gid)
        )
        side.currentIndexChanged.connect(
            lambda _index, gid=group_id: self._notify_changed(gid)
        )
        add_condition.clicked.connect(
            lambda _checked=False, gid=group_id: self.add_condition_to_group_id(gid)
        )
        delete_group.clicked.connect(
            lambda _checked=False, gid=group_id: self._remove_group(gid)
        )
        return card

    def set_rules(self, rules) -> None:
        normalized = list(normalize_rules(rules, kind=self.kind))
        self.blockSignals(True)
        try:
            self._clear_cards()

            grouped: dict[str, list[dict]] = {}
            for rule in normalized:
                grouped.setdefault(rule["group_id"], []).append(rule)

            if not grouped:
                empty = QLabel(
                    "No groups yet. Add a group to define conditions for this section."
                )
                empty.setStyleSheet("color:#7b8794; padding:10px")
                self.cards_layout.addWidget(empty)
                self.cards_layout.addStretch()
                return

            for index, (group_id, group_rules) in enumerate(grouped.items()):
                if index:
                    or_label = QLabel("OR")
                    or_label.setAlignment(Qt.AlignCenter)
                    or_label.setStyleSheet(
                        "color:#52606d; font-weight:700; padding:1px"
                    )
                    self.cards_layout.addWidget(or_label)
                self.cards_layout.addWidget(
                    self._make_group_card(group_id, group_rules)
                )

            self.cards_layout.addStretch()
            for group_id in grouped:
                self._refresh_group_preview(group_id)
        finally:
            self.blockSignals(False)

    def _find_row(self, rule_id: str) -> dict | None:
        return next((row for row in self._rows if row["id"] == rule_id), None)

    def _refresh_upper_for_row(self, row: dict) -> None:
        evidence = row["evidence"]
        operator = row["operator"]
        upper = row["upper"]
        categorical = is_categorical_evidence(evidence.currentData())
        enabled = (
            not categorical
            and operator.currentData() in {"BETWEEN", "OUTSIDE"}
        )
        upper.setEnabled(enabled)
        upper.setVisible(enabled)

    def _refresh_upper_by_id(self, rule_id: str) -> None:
        row = self._find_row(rule_id)
        if row is not None:
            self._refresh_upper_for_row(row)
            self._notify_changed(row["group_id"])

    def _replace_condition_widget(
        self, row: dict, key: str, widget: QWidget, layout_index: int
    ) -> None:
        old = row[key]
        row["layout"].replaceWidget(old, widget)
        old.deleteLater()
        row[key] = widget
        item = row["layout"].takeAt(layout_index)
        row["layout"].insertWidget(layout_index, widget)

    def _evidence_changed(self, rule_id: str) -> None:
        row = self._find_row(rule_id)
        if row is None:
            return

        evidence_name = row["evidence"].currentData()
        default = new_rule(kind=self.kind, evidence=evidence_name)
        operator = self._operator(evidence_name, default["operator"])
        operator.setMinimumWidth(90)
        value = self._value(evidence_name, default["value"])
        upper = self._upper(evidence_name, default["value2"])

        old_operator = row["operator"]
        old_value = row["value"]
        old_upper = row["upper"]
        row["layout"].replaceWidget(old_operator, operator)
        row["layout"].replaceWidget(old_value, value)
        row["layout"].replaceWidget(old_upper, upper)
        old_operator.deleteLater()
        old_value.deleteLater()
        old_upper.deleteLater()
        row["operator"] = operator
        row["value"] = value
        row["upper"] = upper

        self._connect_control(operator, row["group_id"])
        self._connect_control(value, row["group_id"])
        if isinstance(upper, QDoubleSpinBox):
            self._connect_control(upper, row["group_id"])
        operator.currentIndexChanged.connect(
            lambda _index, rid=rule_id: self._refresh_upper_by_id(rid)
        )
        self._refresh_upper_for_row(row)
        self._notify_changed(row["group_id"])

    def _condition_text(self, row: dict) -> str:
        evidence = row["evidence"].currentText()
        operator = row["operator"].currentText()
        value_widget = row["value"]
        if isinstance(value_widget, QComboBox):
            value = value_widget.currentText()
        else:
            value = f"{value_widget.value():g}"

        text = f"{evidence} {operator} {value}"
        if (
            row["operator"].currentData() in {"BETWEEN", "OUTSIDE"}
            and isinstance(row["upper"], QDoubleSpinBox)
        ):
            text += f" and {row['upper'].value():g}"
        return text

    def _refresh_group_preview(self, group_id: str) -> None:
        group = self._groups.get(group_id)
        if group is None:
            return
        parts = [
            self._condition_text(row)
            for row in self._rows
            if row["group_id"] == group_id
        ]
        prefix = {
            "REQUIRED": "Qualify when",
            "VETO": "Reject when",
            "FLIP": "Flip direction when",
        }[self.kind]
        group["preview"].setText(
            f"{prefix}: " + " AND ".join(parts) if parts else f"{prefix}: —"
        )

    def _notify_changed(self, group_id: str | None = None) -> None:
        if group_id is None:
            for current in self._groups:
                self._refresh_group_preview(current)
        else:
            self._refresh_group_preview(group_id)
        self.changed.emit()

    def rules(self) -> tuple[dict, ...]:
        result = []
        for row in self._rows:
            group = self._groups[row["group_id"]]
            evidence = row["evidence"]
            operator = row["operator"]
            value = row["value"]
            upper = row["upper"]
            evidence_name = evidence.currentData()
            categorical = is_categorical_evidence(evidence_name)
            result.append(
                normalize_rule(
                    {
                        "id": row["id"],
                        "group_id": row["group_id"],
                        "group_name": group["name"].text(),
                        "kind": self.kind,
                        "evidence": evidence_name,
                        "operator": operator.currentData(),
                        "value": (
                            value.currentData() if categorical else value.value()
                        ),
                        "value2": (
                            None
                            if categorical or not isinstance(upper, QDoubleSpinBox)
                            else upper.value()
                        ),
                        "regime": group["regime"].currentData(),
                        "side": group["side"].currentData(),
                    },
                    expected_kind=self.kind,
                )
            )
        return tuple(result)

    def rowCount(self) -> int:
        """Compatibility helper for callers/tests from the previous table UI."""
        return len(self._rows)

    def cellWidget(self, row: int, column: int):
        """Expose logical row controls while the visual surface uses cards."""
        if row < 0 or row >= len(self._rows):
            return None
        item = self._rows[row]
        group = self._groups[item["group_id"]]
        mapping = {
            0: group["name"],
            1: item["evidence"],
            2: item["operator"],
            3: item["value"],
            4: item["upper"],
            5: group["regime"],
            6: group["side"],
        }
        return mapping.get(column)

    def selectRow(self, row: int) -> None:
        """Compatibility selection used by non-card callers."""
        if 0 <= row < len(self._rows):
            self._selected_row = row

    def group_count(self) -> int:
        return len(self._groups)

    def _next_group_name(self) -> str:
        label = {"REQUIRED": "Entry", "VETO": "Veto", "FLIP": "Flip"}[self.kind]
        existing = {
            group["name"].text().strip()
            for group in self._groups.values()
        }
        number = self.group_count() + 1
        candidate = f"{label} Group {number}"
        while candidate in existing:
            number += 1
            candidate = f"{label} Group {number}"
        return candidate

    def _focus_rule(self, rule_id: str) -> None:
        row = self._find_row(rule_id)
        if row is None:
            return
        row["evidence"].setFocus()
        self.scroll.ensureWidgetVisible(row["widget"], 20, 20)

    def add_group(self) -> None:
        rules = list(self.rules())
        rule = new_rule(kind=self.kind, group_name=self._next_group_name())
        rules.insert(0, rule)
        self.set_rules(rules)
        self._selected_row = 0
        QTimer.singleShot(0, lambda rid=rule["id"]: self._focus_rule(rid))
        self.changed.emit()

    def add_condition_to_group_id(self, group_id: str) -> None:
        rules = list(self.rules())
        target = next(
            (rule for rule in rules if rule["group_id"] == group_id),
            None,
        )
        if target is None:
            self.add_group()
            return

        condition = new_rule(
            kind=self.kind,
            group_id=target["group_id"],
            group_name=target["group_name"],
            regime=target["regime"],
            side=target["side"],
        )
        insert_at = next(
            index
            for index, rule in enumerate(rules)
            if rule["group_id"] == group_id
        )
        rules.insert(insert_at, condition)
        self.set_rules(rules)
        self._selected_row = next(
            index for index, row in enumerate(self._rows)
            if row["id"] == condition["id"]
        )
        QTimer.singleShot(
            0, lambda rid=condition["id"]: self._focus_rule(rid)
        )
        self.changed.emit()

    def add_condition_to_group(self) -> None:
        """Compatibility action; card buttons call the group-specific version."""
        if not self._rows:
            self.add_group()
            return
        row = (
            self._selected_row
            if self._selected_row is not None
            and 0 <= self._selected_row < len(self._rows)
            else 0
        )
        self.add_condition_to_group_id(self._rows[row]["group_id"])

    def _remove_condition(self, rule_id: str) -> None:
        rules = [rule for rule in self.rules() if rule["id"] != rule_id]
        self.set_rules(rules)
        self.changed.emit()

    def _remove_group(self, group_id: str) -> None:
        rules = [
            rule for rule in self.rules()
            if rule["group_id"] != group_id
        ]
        self.set_rules(rules)
        self.changed.emit()

    def remove_selected(self) -> None:
        """Compatibility action retained for callers from the previous UI."""
        if (
            self._selected_row is None
            or self._selected_row < 0
            or self._selected_row >= len(self._rows)
        ):
            return
        self._remove_condition(self._rows[self._selected_row]["id"])


class RuleStrategyBuilder(QWidget):
    """One strategy thesis expressed as permissions + scoped rules."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        summary_box = QGroupBox("Strategy Summary")
        summary_layout = QHBoxLayout(summary_box)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(
            "font-weight:600; background:#f7f9fb; padding:8px; border:1px solid #d9e2ec"
        )
        summary_layout.addWidget(self.summary, 1)
        layout.addWidget(summary_box)

        direction_box = QGroupBox("1. Signal Strategy & Market Eligibility")
        direction_layout = QVBoxLayout(direction_box)
        direction_form = QFormLayout()
        self.direction_mode = QComboBox()
        for mode in DIRECTION_MODES:
            self.direction_mode.addItem(DIRECTION_LABELS[mode], mode)
        direction_form.addRow("Signal strategy", self.direction_mode)
        direction_layout.addLayout(direction_form)

        permission = QGridLayout()
        permission.addWidget(QLabel("Market state"), 0, 0)
        permission.addWidget(QLabel("LONG"), 0, 1)
        permission.addWidget(QLabel("SHORT"), 0, 2)
        self.permission_checks: dict[str, QCheckBox] = {}
        for row, regime in enumerate(REGIMES, 1):
            permission.addWidget(QLabel(regime.title()), row, 0)
            for column, side in enumerate(SIDES, 1):
                key = f"{regime}_{side}"
                check = QCheckBox("Trade")
                check.setChecked(True)
                self.permission_checks[key] = check
                permission.addWidget(check, row, column)
                check.toggled.connect(lambda _checked: self._notify())
        direction_layout.addLayout(permission)
        note = QLabel(
            "These are permissions only. DI Direction uses raw +DI/-DI side selection. "
            "DMI Trend keeps that side selection and adds built-in ADX ≥ 20, non-falling ADX, "
            "and expanding DI pressure. MACD Pullback creates a candidate only on a fresh 12/26/9 "
            "MACD crossover: bullish below zero or bearish above zero. EMA and S/R confirmation "
            "remain optional Entry/Veto evidence so their value can be measured rather than assumed."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#52606d")
        direction_layout.addWidget(note)
        layout.addWidget(direction_box)

        required_box = QGroupBox(
            "2. Entry Groups — ALL conditions inside; ANY group may qualify"
        )
        required_layout = QVBoxLayout(required_box)
        self.required_rules = RuleTable("REQUIRED")
        required_layout.addWidget(self.required_rules)
        row = QHBoxLayout()
        add = QPushButton("+ Add Entry Group")
        add.setToolTip("Add a new Entry group at the top")
        add.clicked.connect(self.required_rules.add_group)
        row.addWidget(add)
        row.addStretch()
        required_layout.addLayout(row)
        evidence_note = QLabel(
            "Condition Groups are intentionally simple: conditions inside one group are ANDed; Entry groups are alternatives, so any complete Entry group may qualify. Market and Side belong to the group header. New groups and new conditions appear at the top, and each card has its own Add condition and Delete group controls. Evidence is grouped and searchable; Mean Reversion and common S/R choices are shown before advanced details. MR Trade-Direction Stretch is positive when price is extended in the candidate trade direction, for both LONG and SHORT. OI, Funding, Basis and Taker Flow use causal prepared research when local coverage exists. Missing REQUIRED evidence fails that Entry group; missing VETO evidence does not create a rejection. Any MR or S/R rule automatically enables its causal calculation; configure calculation settings on Research Features."
        )
        evidence_note.setWordWrap(True)
        evidence_note.setStyleSheet("color:#52606d")
        required_layout.addWidget(evidence_note)
        layout.addWidget(required_box)

        veto_box = QGroupBox(
            "3. Avoid / Veto Groups — ALL conditions inside; ANY group vetoes"
        )
        veto_layout = QVBoxLayout(veto_box)
        self.veto_rules = RuleTable("VETO")
        veto_layout.addWidget(self.veto_rules)
        row = QHBoxLayout()
        add = QPushButton("+ Add Veto Group")
        add.setToolTip("Add a new Veto group at the top")
        add.clicked.connect(self.veto_rules.add_group)
        row.addWidget(add)
        row.addStretch()
        veto_layout.addLayout(row)
        layout.addWidget(veto_box)

        research_box = QGroupBox("4. Research-only Evidence")
        research_layout = QHBoxLayout(research_box)
        self.enable_mr = QCheckBox("Attach Mean Reversion context")
        self.enable_mr.setChecked(True)
        research_layout.addWidget(self.enable_mr)
        self.research_status = QLabel(
            "S/R · OI · Funding · Positioning/Basis · Taker Flow are rule-ready. Detailed Trade Flow · Order Book remain Analyze Only until dedicated rule dependencies are added."
        )
        self.research_status.setWordWrap(True)
        self.research_status.setStyleSheet("color:#52606d")
        research_layout.addWidget(self.research_status, 1)
        layout.addWidget(research_box)

        self.show_advanced = QCheckBox("Show advanced direction actions and entry timing")
        layout.addWidget(self.show_advanced)
        self.advanced = QGroupBox("5. Advanced")
        advanced_layout = QVBoxLayout(self.advanced)
        advanced_note = QLabel(
            "Direction Flip Groups use the same condition-group model: ALL conditions inside a group must match, and ANY complete Flip group may trigger. Entry timing is separate from evidence filters."
        )
        advanced_note.setWordWrap(True)
        advanced_note.setStyleSheet("color:#52606d")
        advanced_layout.addWidget(advanced_note)
        self.flip_rules = RuleTable("FLIP")
        advanced_layout.addWidget(self.flip_rules)
        row = QHBoxLayout()
        add = QPushButton("+ Add Flip Group")
        add.setToolTip("Add a new Flip group at the top")
        add.clicked.connect(self.flip_rules.add_group)
        row.addWidget(add)
        row.addStretch()
        advanced_layout.addLayout(row)

        timing_form = QFormLayout()
        self.entry_mode = QComboBox()
        self.entry_mode.addItem("Wait until current trade closes", "WAIT_UNTIL_CLOSED")
        self.entry_mode.addItem("Every N strategy candles", "EVERY_N_CANDLES")
        self.entry_interval = QSpinBox()
        self.entry_interval.setRange(1, 1_000_000)
        self.entry_interval.setValue(1)
        self.enable_daily_schedule = QCheckBox()
        self.daily_entry_time = QComboBox()
        for hour in range(24):
            self.daily_entry_time.addItem(f"{hour:02d}:00", f"{hour:02d}:00")
        self.daily_entry_timezone = QComboBox()
        self.daily_entry_timezone.setEditable(True)
        self.daily_entry_timezone.addItem("UTC", "UTC")
        self.daily_missed_policy = QComboBox()
        self.daily_missed_policy.addItem("Skip day", "SKIP_DAY")
        self.daily_missed_policy.addItem("Next available candle", "NEXT_AVAILABLE_CANDLE")
        self.momentum_lookback_hours = QSpinBox()
        self.momentum_lookback_hours.setRange(1, 87600)
        self.momentum_lookback_hours.setValue(24)
        self.momentum_lookback_hours.setSuffix(" h")
        timing_form.addRow("Entry cadence", self.entry_mode)
        timing_form.addRow("Entry interval", self.entry_interval)
        timing_form.addRow("Daily schedule", self.enable_daily_schedule)
        timing_form.addRow("Daily entry time", self.daily_entry_time)
        timing_form.addRow("Timezone", self.daily_entry_timezone)
        timing_form.addRow("Missed schedule", self.daily_missed_policy)
        timing_form.addRow("Momentum rule lookback", self.momentum_lookback_hours)
        advanced_layout.addLayout(timing_form)
        self.advanced.setVisible(False)
        self.show_advanced.toggled.connect(self.advanced.setVisible)
        layout.addWidget(self.advanced)
        layout.addStretch()

        for widget in (
            self.direction_mode,
            self.enable_mr,
            self.entry_mode,
            self.entry_interval,
            self.enable_daily_schedule,
            self.daily_entry_time,
            self.daily_entry_timezone,
            self.daily_missed_policy,
            self.momentum_lookback_hours,
        ):
            signal = (
                widget.toggled
                if isinstance(widget, QCheckBox)
                else widget.valueChanged
                if isinstance(widget, (QSpinBox, QDoubleSpinBox))
                else widget.currentIndexChanged
            )
            signal.connect(lambda *_args: self._notify())
        for table in (self.required_rules, self.veto_rules, self.flip_rules):
            table.changed.connect(self._notify)
        self._notify()

    def _notify(self):
        self.refresh_summary()
        self.changed.emit()

    def market_permissions(self) -> tuple[str, ...]:
        return tuple(
            key
            for key in MARKET_PERMISSIONS
            if self.permission_checks[key].isChecked()
        )

    def refresh_summary(self):
        markets = []
        permissions = set(self.market_permissions())
        for regime in REGIMES:
            sides = [
                side.title()
                for side in SIDES
                if f"{regime}_{side}" in permissions
            ]
            markets.append(f"{regime.title()} {'/'.join(sides) if sides else 'Off'}")
        self.summary.setText(
            f"{DIRECTION_LABELS[self.direction_mode.currentData()]}  ·  "
            f"{' · '.join(markets)}  ·  "
            f"{self.required_rules.group_count()} entry group(s) / "
            f"{len(self.required_rules.rules())} condition(s)  ·  "
            f"{self.veto_rules.group_count()} veto group(s) / "
            f"{len(self.veto_rules.rules())} condition(s)"
        )

    def set_from_strategy(self, strategy) -> None:
        profiles = strategy.profiles
        mode = infer_direction_mode(profiles)
        self.direction_mode.setCurrentIndex(
            max(0, self.direction_mode.findData(mode))
        )
        enabled = set(infer_market_permissions(profiles, mode))
        for key, check in self.permission_checks.items():
            check.setChecked(key in enabled)
        recovered = decompile_rules(profiles)
        self.required_rules.set_rules(recovered["REQUIRED"])
        self.veto_rules.set_rules(recovered["VETO"])
        self.flip_rules.set_rules(recovered["FLIP"])

        self.enable_mr.setChecked(bool(strategy.enable_mean_reversion_analysis))
        self.entry_mode.setCurrentIndex(
            max(0, self.entry_mode.findData(strategy.entry_mode))
        )
        self.entry_interval.setValue(int(strategy.entry_interval))
        self.enable_daily_schedule.setChecked(
            bool(strategy.enable_daily_entry_schedule)
        )
        time_index = self.daily_entry_time.findData(strategy.daily_entry_time)
        if time_index < 0:
            self.daily_entry_time.addItem(
                strategy.daily_entry_time, strategy.daily_entry_time
            )
            time_index = self.daily_entry_time.count() - 1
        self.daily_entry_time.setCurrentIndex(time_index)
        tz_index = self.daily_entry_timezone.findData(strategy.daily_entry_timezone)
        if tz_index < 0:
            self.daily_entry_timezone.addItem(
                strategy.daily_entry_timezone, strategy.daily_entry_timezone
            )
            tz_index = self.daily_entry_timezone.count() - 1
        self.daily_entry_timezone.setCurrentIndex(tz_index)
        self.daily_missed_policy.setCurrentIndex(
            max(
                0,
                self.daily_missed_policy.findData(
                    strategy.daily_entry_missed_policy
                ),
            )
        )
        if profiles:
            first = next(iter(profiles.values()))
            self.momentum_lookback_hours.setValue(
                int(first.momentum_lookback_hours)
            )
        self.refresh_summary()

    def strategy_values(self) -> dict:
        return {
            "direction_mode": self.direction_mode.currentData(),
            "market_permissions": self.market_permissions(),
            "required_rules": self.required_rules.rules(),
            "veto_rules": self.veto_rules.rules(),
            "flip_rules": self.flip_rules.rules(),
            "momentum_lookback_hours": self.momentum_lookback_hours.value(),
            "enable_di_direction_selection": True,
            # DI pressure stays available as causal evidence/reporting. The old
            # global allow-list is deliberately neutral; Entry/Veto rules own any
            # effect on trading decisions.
            "enable_di_pressure_analysis": True,
            "di_pressure_allow_expanding": True,
            "di_pressure_allow_contracting": True,
            "di_pressure_allow_mixed": True,
            "enable_mean_reversion_analysis": self.enable_mr.isChecked(),
            # S/R presets are retired from the rule-based runtime. S/R can still
            # be calculated for research, but entry effects belong only to rules.
            "sr_filter_mode": "ANALYSIS_ONLY",
            "sr_long_avoid_near_resistance": False,
            "sr_long_require_near_support": False,
            "sr_long_block_broken_support": False,
            "sr_long_min_room_to_resistance_atr": 0.0,
            "sr_short_avoid_near_support": False,
            "sr_short_require_near_resistance": False,
            "sr_short_block_broken_resistance": False,
            "sr_short_min_room_to_support_atr": 0.0,
            "entry_mode": self.entry_mode.currentData(),
            "entry_interval": self.entry_interval.value(),
            "enable_daily_entry_schedule": self.enable_daily_schedule.isChecked(),
            "daily_entry_time": self.daily_entry_time.currentData(),
            "daily_entry_timezone": (
                self.daily_entry_timezone.currentData()
                or self.daily_entry_timezone.currentText()
            ),
            "daily_entry_missed_policy": self.daily_missed_policy.currentData(),
        }

    def set_feature_status(self, features) -> None:
        items = [
            "S/R ON" if features.enable_support_resistance_analysis else "S/R Off",
            "OI",
            "Funding",
            "Positioning/Basis",
            "Taker Flow",
        ]
        items.append(
            "Trade Flow ON" if features.trade_flow_enabled else "Trade Flow Off"
        )
        items.append(
            "Order Book ON" if features.order_book_enabled else "Order Book Off"
        )
        self.research_status.setText(
            " · ".join(items)
            + " — S/R and lightweight futures context are rule-ready; detailed Trade Flow and Order Book remain research-only."
        )
