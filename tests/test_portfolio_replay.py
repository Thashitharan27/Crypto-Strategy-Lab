from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from crypto_strategy_lab.feature_research import _write_parquet_atomic
from crypto_strategy_lab.portfolio_replay import (
    inspect_resilience_run,
    run_portfolio_replay,
)
from crypto_strategy_lab.run_manifest import (
    FEATURE_RESEARCH_ARTIFACT_CONTRACT,
    FEATURE_RESEARCH_ARTIFACT_VERSION,
    RUN_MANIFEST_CONTRACT,
    RUN_MANIFEST_VERSION,
    RunArtifactError,
    atomic_json,
    file_sha256,
)


def _sample(sample_id, signal_index, entry, exit_, r, side="LONG"):
    return {
        "research_sample_id": sample_id,
        "research_sampling_version": "STRATEGY_OPPORTUNITY_V1",
        "research_sampling_mode": "EVERY_VIABLE_ENTRY",
        "research_episode_id": f"episode-{signal_index:06d}",
        "research_episode_entry_number": 1,
        "research_episode_viable_entries": 1,
        "research_signal_index": signal_index,
        "strategy_profile_key": "bull_long",
        "side": side,
        "entry_time": pd.Timestamp(entry, tz="UTC"),
        "exit_time": pd.Timestamp(exit_, tz="UTC"),
        "pair_net_r": float(r),
        "pair_net_pnl": float(r) * 10.0,
    }


def _write_run(
    root: Path,
    symbol: str,
    samples: list[dict],
    *,
    start="2024-01-01T00:00:00+00:00",
    end="2024-01-05T00:00:00+00:00",
    mode="EVERY_VIABLE_ENTRY",
) -> Path:
    run_dir = root / f"{symbol}_1d_test"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    frame = pd.DataFrame(samples)
    if not frame.empty:
        frame["research_sampling_mode"] = mode
    path = artifacts / "research_sampling_trades.parquet"
    _write_parquet_atomic(frame, path)
    manifest = {
        "run_manifest_contract": RUN_MANIFEST_CONTRACT,
        "run_manifest_version": RUN_MANIFEST_VERSION,
        "run_status": "COMPLETED",
        "run_id": f"{symbol.lower()}-run",
        "run_completed_at": "2024-01-05T01:00:00+00:00",
        "request": {
            "symbol": symbol,
            "start": start,
            "end": end,
            "requested_strategy_interval": "1d",
            "requested_intrabar_interval": "1m",
        },
        "hashes": {
            "strategy_hash": f"strategy-{symbol}",
            "execution_hash": f"execution-{symbol}",
            "feature_config_hash": f"features-{symbol}",
            "data_config_hash": f"data-{symbol}",
        },
        "artifacts": {
            "research_sampling_trades": {
                "path": "artifacts/research_sampling_trades.parquet",
                "format": "parquet",
                "rows": len(frame),
                "sha256": file_sha256(path),
            }
        },
        "research": {
            "artifact_contract": FEATURE_RESEARCH_ARTIFACT_CONTRACT,
            "artifact_version": FEATURE_RESEARCH_ARTIFACT_VERSION,
            "strategy_research_sampling": {
                "enabled": True,
                "mode": mode,
                "selected_rows": len(frame),
            },
        },
    }
    atomic_json(run_dir / "run_manifest.json", manifest)
    return run_dir


def test_every_viable_replay_can_accept_later_symbol_candidate_after_earlier_one_was_blocked(tmp_path):
    a = _write_run(
        tmp_path,
        "AAAUSDT",
        [
            _sample("a1", 1, "2024-01-01 10:00", "2024-01-04 10:00", 1.0),
            _sample("a2", 2, "2024-01-02 10:00", "2024-01-02 11:00", 1.0),
        ],
    )
    b = _write_run(
        tmp_path,
        "BBBUSDT",
        [_sample("b1", 1, "2024-01-01 09:00", "2024-01-01 23:00", 0.0)],
    )

    summary, candidates, realized, _output = run_portfolio_replay(
        [a, b],
        output_root=tmp_path / "portfolio",
        initial_equity=1000.0,
        risk_per_trade=0.01,
        maximum_total_risk=0.01,
        maximum_open_positions=5,
        one_active_trade_per_symbol=True,
    )

    a1 = candidates.loc[candidates["research_sample_id"].eq("a1")].iloc[0]
    a2 = candidates.loc[candidates["research_sample_id"].eq("a2")].iloc[0]
    assert not bool(a1["portfolio_accepted"])
    assert a1["portfolio_block_reason"] == "MAXIMUM_TOTAL_PORTFOLIO_RISK"
    assert bool(a2["portfolio_accepted"])
    assert summary["accepted_trades"] == 2
    assert set(realized["asset"]) == {"AAAUSDT", "BBBUSDT"}
    assert summary["ending_equity"] == pytest.approx(1010.0)


def test_one_active_trade_per_symbol_reconstructs_realistic_symbol_occupancy(tmp_path):
    a = _write_run(
        tmp_path,
        "AAAUSDT",
        [
            _sample("a1", 1, "2024-01-01 10:00", "2024-01-03 10:00", 1.0),
            _sample("a2", 2, "2024-01-02 10:00", "2024-01-02 11:00", 1.0),
        ],
    )
    b = _write_run(
        tmp_path,
        "BBBUSDT",
        [_sample("b1", 1, "2024-01-04 10:00", "2024-01-04 11:00", 1.0)],
    )

    summary, candidates, _realized, _output = run_portfolio_replay(
        [a, b],
        output_root=tmp_path / "portfolio",
        initial_equity=1000.0,
        risk_per_trade=0.01,
        maximum_total_risk=0.05,
        maximum_open_positions=5,
        one_active_trade_per_symbol=True,
    )

    a2 = candidates.loc[candidates["research_sample_id"].eq("a2")].iloc[0]
    assert not bool(a2["portfolio_accepted"])
    assert a2["portfolio_block_reason"] == "SYMBOL_ACTIVE"
    assert summary["blocked_by_reason"]["SYMBOL_ACTIVE"] == 1


def test_exit_at_same_timestamp_frees_capacity_before_new_entry(tmp_path):
    a = _write_run(
        tmp_path,
        "AAAUSDT",
        [_sample("a1", 1, "2024-01-01 10:00", "2024-01-02 10:00", 0.0)],
    )
    b = _write_run(
        tmp_path,
        "BBBUSDT",
        [_sample("b1", 1, "2024-01-02 10:00", "2024-01-02 11:00", 1.0)],
    )

    summary, candidates, _realized, _output = run_portfolio_replay(
        [a, b],
        output_root=tmp_path / "portfolio",
        risk_per_trade=0.01,
        maximum_total_risk=0.01,
    )

    b1 = candidates.loc[candidates["research_sample_id"].eq("b1")].iloc[0]
    assert bool(b1["portfolio_accepted"])
    assert summary["same_timestamp_exit_policy"] == "PROCESS_EXITS_BEFORE_ENTRIES"


def test_common_period_only_marks_candidates_outside_shared_coverage(tmp_path):
    a = _write_run(
        tmp_path,
        "AAAUSDT",
        [
            _sample("a0", 0, "2024-01-01 10:00", "2024-01-01 11:00", 1.0),
            _sample("a1", 1, "2024-01-02 10:00", "2024-01-02 11:00", 1.0),
        ],
        start="2024-01-01T00:00:00+00:00",
        end="2024-01-05T00:00:00+00:00",
    )
    b = _write_run(
        tmp_path,
        "BBBUSDT",
        [_sample("b1", 1, "2024-01-02 12:00", "2024-01-02 13:00", 1.0)],
        start="2024-01-02T00:00:00+00:00",
        end="2024-01-04T00:00:00+00:00",
    )

    summary, candidates, _realized, _output = run_portfolio_replay(
        [a, b], output_root=tmp_path / "portfolio", common_period_only=True
    )

    a0 = candidates.loc[candidates["research_sample_id"].eq("a0")].iloc[0]
    assert not bool(a0["portfolio_in_scope"])
    assert a0["portfolio_block_reason"] == "OUTSIDE_REPLAY_PERIOD"
    assert summary["replay_period_start"].startswith("2024-01-02")
    assert summary["replay_period_end"].startswith("2024-01-04")


def test_portfolio_replay_rejects_non_every_viable_sampling_run(tmp_path):
    run = _write_run(
        tmp_path,
        "AAAUSDT",
        [_sample("a1", 1, "2024-01-01 10:00", "2024-01-01 11:00", 1.0)],
        mode="EPISODE_FIRST",
    )
    with pytest.raises(RunArtifactError, match="Every Viable Entry"):
        inspect_resilience_run(run)
