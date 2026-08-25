from crypto_strategy_lab.gui.rule_strategy_builder import EVIDENCE_GROUPS, EVIDENCE_LABELS


def test_directional_di_is_a_separate_directional_builder_option():
    assert EVIDENCE_LABELS["DIRECTIONAL_DI"] == "Directional DI"
    directional_group = dict(EVIDENCE_GROUPS)["Directional / DI"]
    assert "DIRECTIONAL_DI" in directional_group
    assert "DIRECTIONAL_DI_CHANGE" in directional_group
    assert directional_group.index("DIRECTIONAL_DI") != directional_group.index(
        "DIRECTIONAL_DI_CHANGE"
    )
