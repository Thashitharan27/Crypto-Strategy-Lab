"""Rule-based researcher GUI built on the stable v2 application shell.

The shell/data/results plumbing stays unchanged.  Strategy authoring and trade
management are replaced with a single rule-based thesis and one base execution
configuration; mature six-way engine inputs are generated only when building the
run config.
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout, QWidget

from crypto_strategy_lab.data_lake_config import ExecutionProfileConfig
from crypto_strategy_lab.strategy_rule_model import (
    common_execution_profile,
    compile_profiles,
)
from .rule_strategy_builder import DIRECTION_LABELS, RuleStrategyBuilder
from .v2_main_window import (
    DataclassForm,
    EXECUTION_PROFILE_GROUPS,
    MainWindow as LegacyMainWindow,
    TIMEFRAME_LABELS,
    display_percentage,
    timeframe_label,
)


class MainWindow(LegacyMainWindow):
    """Authoritative desktop GUI with profile-free strategy authoring."""

    def __init__(self, startup_status=None, service=None):
        # LegacyMainWindow supplies the battle-tested setup/data/results/reporting
        # shell.  During this call our guarded overrides delegate back until the
        # rule widgets exist.
        super().__init__(startup_status=startup_status, service=service)

        self.rule_builder = RuleStrategyBuilder()
        self.base_execution_form = DataclassForm(
            ExecutionProfileConfig(), groups=EXECUTION_PROFILE_GROUPS
        )
        self._replace_strategy_page()
        self._replace_execution_page()
        self.rule_builder.changed.connect(self._refresh_summary_from_widgets)
        self.base_execution_form.changed.connect(self._refresh_summary_from_widgets)
        self.apply_config(self.config)

    def _replace_page(self, index: int, page: QWidget) -> None:
        old = self.pages.widget(index)
        was_current = self.pages.currentIndex() == index
        self.pages.removeWidget(old)
        old.deleteLater()
        self.pages.insertWidget(index, page)
        if was_current:
            self.pages.setCurrentIndex(index)

    def _replace_strategy_page(self) -> None:
        page = self._page("Strategy Builder", self._scroll(self.rule_builder))
        self._replace_page(1, page)

    def _replace_execution_page(self) -> None:
        note = QLabel(
            "Risk applies to the shared account. Trade management below is one base execution plan "
            "for the strategy; it is no longer duplicated across Bull/Bear/Sideways profiles."
        )
        note.setWordWrap(True)
        note.setStyleSheet("background:#eef5fb; padding:8px; border:1px solid #c8d9e8")

        management = QGroupBox("Base Trade Management")
        management_layout = QVBoxLayout(management)
        management_layout.addWidget(self.base_execution_form)

        page = self._page(
            "Risk & Execution",
            note,
            self._scroll(self.execution_form),
            self._scroll(management),
            self._risk_explanation(),
        )
        self._replace_page(3, page)

    def build_config(self):
        if not hasattr(self, "rule_builder"):
            return super().build_config()

        base = super().build_config()
        authored = self.rule_builder.strategy_values()
        base_execution = self.base_execution_form.value(
            common_execution_profile(base.execution.profiles)
        )
        strategy_profiles, execution_profiles = compile_profiles(
            direction_mode=authored.pop("direction_mode"),
            market_permissions=authored.pop("market_permissions"),
            required_rules=authored.pop("required_rules"),
            veto_rules=authored.pop("veto_rules"),
            flip_rules=authored.pop("flip_rules"),
            rsi_period=base.features.mean_reversion_rsi_period,
            momentum_lookback_hours=authored.pop("momentum_lookback_hours"),
            base_execution=base_execution,
        )
        strategy = replace(
            base.strategy,
            profiles=strategy_profiles,
            strategy_profile_run_mode="COMBINED_SHARED_CAPITAL",
            **authored,
        )
        execution = replace(base.execution, profiles=execution_profiles)
        result = replace(base, strategy=strategy, execution=execution)
        result.validate()
        return result

    def apply_config(self, config):
        super().apply_config(config)
        if not hasattr(self, "rule_builder"):
            return
        self.rule_builder.set_from_strategy(config.strategy)
        self.rule_builder.set_feature_status(config.features)
        self.base_execution_form.set_value(
            common_execution_profile(config.execution.profiles)
        )
        self._render_research_summary(config)

    def _refresh_summary_from_widgets(self):
        if not hasattr(self, "rule_builder"):
            return super()._refresh_summary_from_widgets()
        if self._applying_config:
            return
        try:
            config = self.build_config()
            self.rule_builder.set_feature_status(config.features)
            self.rule_builder.refresh_summary()
            self._render_research_summary(config)
        except (ValueError, TypeError, KeyError):
            # Invalid/incomplete edits remain visible in the controls and are
            # reported when Run is pressed; live summary refresh must stay quiet.
            return

    def _render_research_summary(self, config):
        if not hasattr(self, "rule_builder"):
            return super()._render_research_summary(config)

        permissions = self.rule_builder.market_permissions()
        direction = self.rule_builder.direction_mode.currentData()
        required = len(self.rule_builder.required_rules.rules())
        veto = len(self.rule_builder.veto_rules.rules())
        pressure = self.rule_builder.pressure_states()
        pressure_text = (
            "Off" if not pressure
            else "Analyze Only" if len(pressure) == 3
            else ", ".join(item.title() for item in pressure)
        )
        intrabar = (
            f"{config.data.intrabar_timeframe_minutes}m exits"
            if config.data.use_intrabar_data else "bar-close exits"
        )
        risk = display_percentage(config.execution.risk_per_leg)
        base_execution = self.base_execution_form.value(
            common_execution_profile(config.execution.profiles)
        )

        self.current_research.setText(
            f"CURRENT RESEARCH\n\n{self.symbol.currentText() or 'BTCUSDT'}\n"
            f"{timeframe_label(config.data.strategy_timeframe_minutes)} strategy / {intrabar}\n\n"
            f"Direction  {DIRECTION_LABELS[direction]}\n"
            f"Markets  {len(permissions)} of 6 allowed\n"
            f"Entry rules  {required}\nVeto rules  {veto}\n"
            f"DI Pressure  {pressure_text}\n"
            f"MR Context  {'ANALYZE' if config.strategy.enable_mean_reversion_analysis else 'OFF'}\n"
            f"Trade Flow  {'ANALYZE' if config.features.trade_flow_enabled else 'OFF'}\n"
            f"Order Book  {'ANALYZE' if config.features.order_book_enabled else 'OFF'}\n\n"
            f"Base risk  {risk}\nMax trades  {config.execution.max_active_pairs}\n\n"
            f"Data  {self._data_state()}"
        )
        self.risk_explanation.setText(
            f"Base Risk: {risk}. At ${config.execution.initial_equity:,.2f}, planned full-stop "
            f"account risk is ${config.execution.initial_equity * config.execution.risk_per_leg:,.2f}. "
            f"Base stop distance: {base_execution.stop_loss_multiple:g} distance units; "
            f"fixed target: {base_execution.reward_risk_ratio:g}R."
        )

        if hasattr(self, "review_summary"):
            allowed = ", ".join(item.replace("_", " ").title() for item in permissions) or "None"
            self.review_summary.setText(
                f"{self.symbol.currentText() or 'BTCUSDT'} — "
                f"{TIMEFRAME_LABELS[timeframe_label(config.data.strategy_timeframe_minutes)]} Research\n\n"
                f"Direction: {DIRECTION_LABELS[direction]}\n"
                f"Allowed markets/sides: {allowed}\n"
                f"Entry rules: {required} required · {veto} veto\n"
                f"DI pressure: {pressure_text}\n"
                f"Mean Reversion: {'Analyze Only' if config.strategy.enable_mean_reversion_analysis else 'Off'}\n"
                f"Support / Resistance: {'Veto / Avoid' if config.strategy.sr_filter_mode == 'APPLY_ENTRY_RULES' else 'Analyze Only'}\n\n"
                f"Starting Equity: ${config.execution.initial_equity:,.2f}\n"
                f"Base Risk: {risk}\n"
                f"Stop: {base_execution.stop_loss_multiple:g} distance units · "
                f"Target: {base_execution.reward_risk_ratio:g}R\n"
                f"Maximum Active Trades: {config.execution.max_active_pairs}\n"
                f"Reports: {config.reporting.analysis_level}\n\n"
                f"DATA STATUS: {self._data_state()}"
            )
