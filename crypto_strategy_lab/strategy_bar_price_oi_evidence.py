"""Install strategy-bar Price/OI state as first-class rule evidence.

The futures positioning feature already publishes ``price_oi_state`` using the
strategy-bar price return and strategy-bar open-interest change.  This installer
wires that existing causal field into the current rule model, native simulator,
and researcher-facing evidence selector without changing the separately-defined
1h Price/OI state.

It is intentionally idempotent because the desktop composition layer may import
GUI modules in different orders during tests.
"""
from __future__ import annotations


EVIDENCE_ID = "PRICE_OI_STATE"
EVIDENCE_LABEL = "Price / OI State (Strategy Bar)"
RULE_VALUES = (
    "PRICE_UP_OI_UP",
    "PRICE_UP_OI_DOWN",
    "PRICE_DOWN_OI_UP",
    "PRICE_DOWN_OI_DOWN",
    "UNKNOWN",
)


def _prepend_to_group(groups, target_label: str, evidence: str):
    result = []
    for label, items in groups:
        values = tuple(items)
        if label == target_label:
            values = (evidence, *(item for item in values if item != evidence))
        result.append((label, values))
    return tuple(result)


def _insert_into_menu(items, target_label: str, evidence: str):
    result = []
    for item in items:
        if isinstance(item, str):
            result.append(item)
            continue
        label, children = item
        children = tuple(children)
        if label == target_label:
            children = (evidence, *(child for child in children if child != evidence))
        else:
            children = _insert_into_menu(children, target_label, evidence)
        result.append((label, children))
    return tuple(result)


def install_strategy_bar_price_oi_evidence() -> None:
    """Expose ``price_oi_state`` through the active Entry/Veto rule contract."""
    from crypto_strategy_lab import strategy_profiles

    if EVIDENCE_ID not in strategy_profiles.RULE_INDICATORS:
        indicators = list(strategy_profiles.RULE_INDICATORS)
        try:
            index = indicators.index("OI_VS_PRICE_STATE_1H")
        except ValueError:
            index = len(indicators)
        indicators.insert(index, EVIDENCE_ID)
        strategy_profiles.RULE_INDICATORS = tuple(indicators)

    # Import after updating strategy_profiles so modules that snapshot the tuple
    # during import see the new native evidence ID.
    from crypto_strategy_lab import strategy_rule_model

    strategy_rule_model.RULE_INDICATORS = strategy_profiles.RULE_INDICATORS
    strategy_rule_model.CATEGORICAL_RULE_VALUES[EVIDENCE_ID] = RULE_VALUES
    strategy_rule_model.CATEGORICAL_VALUE_CODES[EVIDENCE_ID] = {
        "PRICE_UP_OI_UP": 1.0,
        "PRICE_UP_OI_DOWN": 2.0,
        "PRICE_DOWN_OI_UP": 3.0,
        "PRICE_DOWN_OI_DOWN": 4.0,
        "UNKNOWN": 5.0,
        # The source feature can also emit FLAT_OR_MIXED when one/both changes
        # are exactly flat. Keep that value internally distinct but do not expose
        # it as one of the requested selectable DOGE research states.
        "FLAT_OR_MIXED": 6.0,
    }

    from crypto_strategy_lab import rule_native_engine

    rule_native_engine._RESEARCH_CATEGORICAL_FIELDS[EVIDENCE_ID] = (
        "futures_positioning",
        "price_oi_state",
    )
    rule_native_engine._RESEARCH_RULE_INDICATORS = frozenset(
        (
            *rule_native_engine._RESEARCH_NUMERIC_FIELDS,
            *rule_native_engine._RESEARCH_CATEGORICAL_FIELDS,
        )
    )

    # The active researcher GUI imports RULE_INDICATORS by value, so update its
    # module-level snapshot as well as the label/category structures.
    from crypto_strategy_lab.gui import rule_strategy_builder

    rule_strategy_builder.RULE_INDICATORS = strategy_profiles.RULE_INDICATORS
    rule_strategy_builder.EVIDENCE_LABELS[EVIDENCE_ID] = EVIDENCE_LABEL
    rule_strategy_builder.EVIDENCE_GROUPS = _prepend_to_group(
        rule_strategy_builder.EVIDENCE_GROUPS,
        "Futures — Open Interest & Positioning",
        EVIDENCE_ID,
    )
    rule_strategy_builder.EVIDENCE_MENU_TREE = _insert_into_menu(
        rule_strategy_builder.EVIDENCE_MENU_TREE,
        "Open Interest & Positioning",
        EVIDENCE_ID,
    )
