from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from crypto_strategy_lab.feature_research import (
    FEATURE_RESEARCH_ARTIFACT_CONTRACT, ResearchArtifactError,
    ResearchQueryService,
)


def _run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    root = run / "research"
    root.mkdir(parents=True)
    times = pd.date_range("2025-01-01", periods=5, freq="4h", tz="UTC")
    context = pd.DataFrame({
        "strategy_index": [0, 1, 2, 3, 4],
        "strategy_candle_open_time": times,
        "decision_available_at": times + pd.Timedelta(hours=4),
        "plus_di": [2., 7., 14., 22., 31.], "minus_di": [31., 22., 14., 7., 2.],
        "market_regime": ["BULL", "BULL", "BEAR", "BEAR", "BULL"],
        "mean_reversion_state": ["NEUTRAL", "EXTREME", "EXTREME", "NEUTRAL", "EXTREME"],
        "open_interest": [100., 101., 102., 103., 104.],
        "price_oi_state": ["UP", "UP", "DOWN", "DOWN", "UP"],
        "funding_rate": [0.01, 0.02, -0.01, 0., 0.03],
        "taker_imbalance": [0.1, 0.2, -0.2, 0., 0.5],
        "trade_flow_delta": [1., 2., -2., 0., 5.],
        "book_depth_imbalance": [0.2, None, -0.1, 0., 0.4],
        "book_depth_covered": [True, False, True, True, True],
    })
    trades = pd.DataFrame({
        "pair_id": range(5), "side": ["LONG"] * 5,
        "entry_time": times + pd.Timedelta(hours=5),
        "exit_time": times + pd.Timedelta(hours=6),
        "pair_net_pnl": [10., -5., 0., 20., -10.],
        "pair_net_r": [1., -0.5, 0., 2., -1.],
        "research_signal_index": [0, 1, 2, 3, 4],
        "research_signal_candle_open_time": times,
        "research_signal_available_at": times + pd.Timedelta(hours=4),
        "open_interest": context.open_interest,
        "funding_rate": context.funding_rate,
    })
    con = duckdb.connect()
    con.register("t", trades); con.execute(f"COPY t TO '{root / 'trades.parquet'}' (FORMAT PARQUET)")
    con.register("c", context); con.execute(f"COPY c TO '{root / 'context.parquet'}' (FORMAT PARQUET)")
    con.close()
    manifest = {
        "artifact_contract": FEATURE_RESEARCH_ARTIFACT_CONTRACT, "artifact_version": 1,
        "request": {"symbol": "BTCUSDT", "start": "2025-01-01", "end": "2025-01-02",
                    "strategy_interval": "4h", "intrabar_interval": "1m"},
        "prepared_cache_key": "unchanged", "feature_cache_identities": {},
        "trade_row_count": 5, "feature_context_row_count": 5,
        "trades_parquet": "trades.parquet", "context_parquet": "context.parquet",
    }
    (root / "research_manifest.json").write_text(json.dumps(manifest))
    return run


def test_duckdb_exact_join_metrics_buckets_missing_and_feature_families(tmp_path, monkeypatch):
    run = _run(tmp_path)
    monkeypatch.setattr(pd, "read_parquet", lambda *a, **k: pytest.fail("pandas parquet read"))
    with ResearchQueryService(run) as service:
        grouped = service.query({"dimensions": [{"column": "market_regime"},
                                                  {"column": "price_oi_state"}]})
        assert grouped.trades.sum() == 5
        bull_up = grouped[(grouped.market_regime == "BULL") & (grouped.price_oi_state == "UP")].iloc[0]
        assert (bull_up.trades, bull_up.wins, bull_up.losses, bull_up.breakeven) == (3, 1, 2, 0)
        assert bull_up.net_r == pytest.approx(-0.5)
        buckets = service.query({"dimensions": [{"column": "directional_di", "alias": "di",
                                                   "boundaries": [0, 5, 10, 15, 20, 25, 30]}]})
        assert set(buckets.di) == {"[0,5)", "[5,10)", "[10,15)", "[20,25)", "[30,+inf)"}
        missing = service.query({"dimensions": [{"column": "book_depth_imbalance"}]})
        assert missing.trades.sum() == 5
        assert missing.loc[missing.book_depth_imbalance == "MISSING", "trades"].item() == 1
        combined = service.query({"dimensions": [{"column": "mean_reversion_state"},
                                                   {"column": "funding_rate"},
                                                   {"column": "taker_imbalance"},
                                                   {"column": "trade_flow_delta"},
                                                   {"column": "book_depth_covered"}]})
        assert combined.trades.sum() == 5


def test_timestamp_and_research_value_parity_are_errors(tmp_path):
    run = _run(tmp_path)
    con = duckdb.connect()
    context = con.execute(f"SELECT * FROM read_parquet('{run / 'research/context.parquet'}')").fetchdf()
    context.loc[1, "decision_available_at"] += pd.Timedelta(minutes=15)
    con.register("c", context); con.execute(f"COPY c TO '{run / 'research/context.parquet'}' (FORMAT PARQUET, OVERWRITE 1)")
    con.close()
    with pytest.raises(ResearchArtifactError, match="availability is invalid|timestamp mismatch"):
        ResearchQueryService(run)

    run = _run(tmp_path / "other")
    con = duckdb.connect()
    trades = con.execute(f"SELECT * FROM read_parquet('{run / 'research/trades.parquet'}')").fetchdf()
    trades.loc[1, "open_interest"] = 999
    con.register("t", trades); con.execute(f"COPY t TO '{run / 'research/trades.parquet'}' (FORMAT PARQUET, OVERWRITE 1)")
    con.close()
    with pytest.raises(ResearchArtifactError, match="research-value mismatch"):
        ResearchQueryService(run)


def test_missing_legacy_artifact_and_unavailable_column_are_explicit(tmp_path):
    with pytest.raises(ResearchArtifactError, match="does not contain Task-16"):
        ResearchQueryService(tmp_path)
    with ResearchQueryService(_run(tmp_path)) as service:
        with pytest.raises(ResearchArtifactError, match="unavailable"):
            service.query({"dimensions": [{"column": "not_enabled"}]})
