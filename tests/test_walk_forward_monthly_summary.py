from __future__ import annotations

import pytest

from crypto_strategy_lab.causal_experiment import CausalExperimentStore


def _definition() -> dict:
    return {
        "symbol": "BTCUSDT",
        "strategy_timeframe": "15m",
        "intrabar_timeframe": "1m",
        "strategy": "DI_DIRECTION",
        "stop_loss": {"type": "ATR", "atr_multiple": 2},
        "take_profit": {"type": "FIXED_R", "reward_risk_ratio": 3},
        "regime_method": "ASSET_RETURN",
        "risk_model": {
            "type": "percent_equity",
            "initial_equity": 1000.0,
            "risk_per_trade": 0.01,
        },
        "reference_run": "BTCUSDT_15m_reference",
        "reference_provenance": {
            "period_start": "2020-06-01T00:00:00+00:00",
            "period_end": "2026-09-01T00:00:00+00:00",
        },
    }


def _append_trade(
    store: CausalExperimentStore,
    head: dict,
    *,
    candidate_id: str,
    resolved_at: str,
    net_r: float,
    equity_before: float,
    equity_after: float,
) -> dict:
    captured = store.append_event(
        "WF_MONTHLY_TEST",
        "CANDIDATE_CONTEXT_CAPTURED",
        {"candidate_id": candidate_id, "feature_hash": f"hash-{candidate_id}"},
        f"{candidate_id}:capture",
        head["sequence"],
        head["state_hash"],
        effective_market_time=resolved_at,
    )
    frozen = store.append_event(
        "WF_MONTHLY_TEST",
        "DECISION_FROZEN",
        {
            "candidate_id": candidate_id,
            "final_action": "LONG",
            "state_hash_at_decision": captured["state_hash"],
        },
        f"{candidate_id}:freeze",
        captured["sequence"],
        captured["state_hash"],
        effective_market_time=resolved_at,
    )
    revealed = store.append_event(
        "WF_MONTHLY_TEST",
        "OUTCOME_REVEALED",
        {"candidate_id": candidate_id, "net_r": net_r},
        f"{candidate_id}:reveal",
        frozen["sequence"],
        frozen["state_hash"],
        effective_market_time=resolved_at,
    )
    return store.append_event(
        "WF_MONTHLY_TEST",
        "TRADE_RESOLVED",
        {
            "candidate_id": candidate_id,
            "ledger": "RESEARCH",
            "result": "WIN" if net_r > 0 else ("LOSS" if net_r < 0 else "BREAKEVEN"),
            "net_r": net_r,
            "net_pnl": equity_after - equity_before,
            "equity_before": equity_before,
            "equity_after": equity_after,
        },
        f"{candidate_id}:resolved",
        revealed["sequence"],
        revealed["state_hash"],
        effective_market_time=resolved_at,
    )


def test_monthly_summary_reads_full_ledger_and_fills_zero_trade_months(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    head = store.create("WF_MONTHLY_TEST", _definition(), "create:monthly")

    head = _append_trade(
        store,
        head,
        candidate_id="june-win",
        resolved_at="2020-06-15T12:00:00+00:00",
        net_r=3.0,
        equity_before=1000.0,
        equity_after=1030.0,
    )
    head = _append_trade(
        store,
        head,
        candidate_id="july-loss",
        resolved_at="2020-07-02T12:00:00+00:00",
        net_r=-1.0,
        equity_before=1030.0,
        equity_after=1019.7,
    )

    summary = store.summarize_monthly(
        "WF_MONTHLY_TEST",
        start_month="2020-06",
        end_month="2020-08",
    )

    assert summary["sequence"] == head["sequence"]
    assert [row["month"] for row in summary["months"]] == [
        "2020-06",
        "2020-07",
        "2020-08",
    ]

    june, july, august = summary["months"]
    assert june["wins"] == 1
    assert june["losses"] == 0
    assert june["trades"] == 1
    assert june["win_rate_pct"] == 100.0
    assert june["net_r"] == 3.0
    assert june["opening_equity"] == 1000.0
    assert june["closing_equity"] == 1030.0

    assert july["wins"] == 0
    assert july["losses"] == 1
    assert july["trades"] == 1
    assert july["net_r"] == -1.0
    assert july["opening_equity"] == 1030.0
    assert july["closing_equity"] == pytest.approx(1019.7)

    assert august["trades"] == 0
    assert august["win_rate_pct"] is None
    assert august["opening_equity"] == pytest.approx(1019.7)
    assert august["closing_equity"] == pytest.approx(1019.7)

    assert summary["totals"]["wins"] == 1
    assert summary["totals"]["losses"] == 1
    assert summary["totals"]["trades"] == 2
    assert summary["totals"]["win_rate_pct"] == 50.0
    assert summary["totals"]["net_r"] == 2.0
    assert summary["totals"]["net_pnl"] == pytest.approx(19.7)
    assert summary["totals"]["opening_equity"] == 1000.0
    assert summary["totals"]["closing_equity"] == pytest.approx(1019.7)


def test_monthly_summary_rejects_bad_month_or_ledger(tmp_path):
    store = CausalExperimentStore(tmp_path / "experiments")
    store.create("WF_MONTHLY_TEST", _definition(), "create:monthly")

    with pytest.raises(ValueError, match="YYYY-MM"):
        store.summarize_monthly("WF_MONTHLY_TEST", start_month="2020-13")

    with pytest.raises(ValueError, match="ledger"):
        store.summarize_monthly("WF_MONTHLY_TEST", ledger="PAPER")
