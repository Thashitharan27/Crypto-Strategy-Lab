from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.feature_research import (
    FEATURE_RESEARCH_ARTIFACT_CONTRACT,
    ResearchArtifactError,
    ResearchQueryService,
    _sr_zone_inventory_frame,
    _validate_sr_zone_inventory,
    write_research_artifacts,
)


@dataclass(frozen=True)
class _ResearchBlock:
    name: str
    available_at: np.ndarray
    values: dict[str, np.ndarray]


@dataclass(frozen=True)
class _Prepared:
    timestamp: np.ndarray
    decision_available_at: np.ndarray
    strategy_interval: pd.Timedelta
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    plus_di: np.ndarray
    minus_di: np.ndarray
    atr_pct: np.ndarray
    market_regime: np.ndarray
    mean_reversion_state: np.ndarray
    momentum_returns_by_hours: dict[int, np.ndarray]
    research: tuple[_ResearchBlock, ...]

    def __len__(self):
        return len(self.timestamp)


def _prepared() -> _Prepared:
    times = pd.date_range("2025-01-01", periods=5, freq="4h", tz="UTC")
    available = times + pd.Timedelta(hours=4)
    n = len(times)
    blocks = (
        _ResearchBlock(
            "futures_positioning",
            available.to_numpy(dtype="datetime64[ns]"),
            {
                "open_interest": np.array([100., 101., 102., 103., 104.]),
                "price_oi_state": np.array(["UP", "UP", "DOWN", "DOWN", "UP"], dtype=object),
            },
        ),
        _ResearchBlock(
            "funding_context",
            available.to_numpy(dtype="datetime64[ns]"),
            {
                "funding_rate": np.array([0.01, 0.02, -0.01, 0., 0.03]),
                "funding_bias": np.array(["POSITIVE", "POSITIVE", "NEGATIVE", "NEUTRAL", "POSITIVE"], dtype=object),
            },
        ),
        _ResearchBlock(
            "taker_flow_context",
            available.to_numpy(dtype="datetime64[ns]"),
            {"taker_imbalance": np.array([0.1, 0.2, -0.2, 0., 0.5])},
        ),
        _ResearchBlock(
            "trade_flow_context",
            available.to_numpy(dtype="datetime64[ns]"),
            {"trade_flow_delta": np.array([1., 2., -2., 0., 5.])},
        ),
        _ResearchBlock(
            "order_book_context",
            available.to_numpy(dtype="datetime64[ns]"),
            {
                "book_depth_imbalance": np.array([0.2, np.nan, -0.1, 0., 0.4]),
                "book_depth_covered": np.array([True, False, True, True, True]),
            },
        ),
        _ResearchBlock(
            "support_resistance_4h",
            available.to_numpy(dtype="datetime64[ns]"),
            {
                "sr_4h_completed_candle_time": available.to_numpy(
                    dtype="datetime64[ns]"
                ),
                "sr_4h_zone_inventory_json": np.array(
                    [
                        json.dumps(
                            [
                                {
                                    "zone_id": "SUPPORT:1",
                                    "structure": "SUPPORT",
                                    "zone_low": 95.0,
                                    "zone_high": 96.0,
                                    "anchor_price": 95.0,
                                    "pivot_bar_index": 1,
                                    "confirmed_at_index": 2,
                                    "source_bar_indices": [1],
                                    "source_count": 1,
                                    "touch_count": 1,
                                    "validation_rejection_atr": 0.8,
                                    "state": "SUPPORT_HELD",
                                    "tested": True,
                                    "held": True,
                                    "rejection_atr": 0.7,
                                    "test_count": 2,
                                    "bars_since_test": 1,
                                    "last_test_index": 1,
                                    "distance_price": 4.0,
                                    "distance_atr": 1.0,
                                    "near": False,
                                    "inside": False,
                                    "nearest": True,
                                },
                                {
                                    "zone_id": "SUPPORT:0",
                                    "structure": "SUPPORT",
                                    "zone_low": 90.0,
                                    "zone_high": 91.0,
                                    "anchor_price": 90.0,
                                    "pivot_bar_index": 0,
                                    "confirmed_at_index": 1,
                                    "source_bar_indices": [0],
                                    "source_count": 1,
                                    "touch_count": 1,
                                    "validation_rejection_atr": 0.6,
                                    "state": "APPROACHING_SUPPORT",
                                    "tested": False,
                                    "held": False,
                                    "rejection_atr": None,
                                    "test_count": 0,
                                    "bars_since_test": None,
                                    "last_test_index": None,
                                    "distance_price": 9.0,
                                    "distance_atr": 2.25,
                                    "near": False,
                                    "inside": False,
                                    "nearest": False,
                                },
                            ],
                            separators=(",", ":"),
                        )
                    ]
                    * n,
                    dtype=object,
                ),
            },
        ),
    )
    return _Prepared(
        timestamp=times.to_numpy(dtype="datetime64[ns]"),
        decision_available_at=available.to_numpy(dtype="datetime64[ns]"),
        strategy_interval=pd.Timedelta(hours=4),
        open=np.full(n, 100.),
        high=np.full(n, 101.),
        low=np.full(n, 99.),
        close=np.arange(n, dtype=float) + 100.,
        volume=np.full(n, 10.),
        plus_di=np.array([2., 7., 14., 22., 31.]),
        minus_di=np.array([31., 22., 14., 7., 2.]),
        atr_pct=np.array([0.01, 0.02, 0.03, 0.04, 0.05]),
        market_regime=np.array(["BULL", "BULL", "BEAR", "BEAR", "BULL"], dtype=object),
        mean_reversion_state=np.array(["NEUTRAL", "EXTREME", "EXTREME", "NEUTRAL", "EXTREME"], dtype=object),
        momentum_returns_by_hours={24: np.array([0.01, 0.02, -0.01, 0., 0.03])},
        research=blocks,
    )


def _trades(prepared: _Prepared) -> pd.DataFrame:
    times = pd.to_datetime(prepared.timestamp, utc=True)
    available = pd.to_datetime(prepared.decision_available_at, utc=True)
    return pd.DataFrame(
        {
            "pair_id": range(5),
            "side": ["LONG"] * 5,
            "entry_time": times + pd.Timedelta(hours=5),
            "exit_time": times + pd.Timedelta(hours=6),
            "pair_net_pnl": [10., -5., 0., 20., -10.],
            "pair_net_r": [1., -0.5, 0., 2., -1.],
            "research_signal_index": [0, 1, 2, 3, 4],
            "research_signal_candle_open_time": times,
            "research_signal_available_at": available,
            "open_interest": [100., 101., 102., 103., 104.],
            "funding_rate": [0.01, 0.02, -0.01, 0., 0.03],
        }
    )


def _write_run(tmp_path: Path, *, empty: bool = False) -> Path:
    run = tmp_path / "run"
    run.mkdir(parents=True)
    prepared = _prepared()
    trades = _trades(prepared)
    if empty:
        trades = trades.iloc[0:0].copy()
    request = SimpleNamespace(
        symbol="BTCUSDT",
        start=pd.Timestamp("2025-01-01T00:00:00Z").to_pydatetime(),
        end=pd.Timestamp("2025-01-02T00:00:00Z").to_pydatetime(),
        strategy_interval="4h",
        intrabar_interval="1m",
    )
    result = SimpleNamespace(
        trades=trades,
        request=request,
        prepared_cache_key="prepared-key",
        feature_cache_metadata={
            "core_directional": {"cache_key": "core"},
            "futures_positioning": {"cache_key": "oi"},
            "funding_context": {"cache_key": "funding"},
        },
    )
    context = SimpleNamespace(prepared=prepared)
    write_research_artifacts(run, result, context)
    return run


def _rehash(run: Path, key: str, path: Path) -> None:
    manifest_path = run / "research" / "research_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["artifact_sha256"][key] = digest
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")



def test_sr_snapshot_fast_path_uses_cached_inventory_metadata(monkeypatch):
    payload = json.dumps(
        [
            {
                "zone_id": "SUPPORT:1",
                "structure": "SUPPORT",
                "zone_low": 95.0,
                "zone_high": 96.0,
                "source_count": 1,
                "test_count": 0,
                "nearest": True,
            }
        ],
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    feature_context = pd.DataFrame(
        {
            "strategy_index": [0],
            "strategy_candle_open_time": [pd.Timestamp("2026-01-01")],
            "decision_available_at": [pd.Timestamp("2026-01-01 00:15:00")],
            "sr_strategy_completed_candle_time": [
                pd.Timestamp("2026-01-01 00:15:00")
            ],
            "sr_strategy_zone_inventory_json": [payload],
            "sr_strategy_zone_inventory_count": [1],
            "sr_strategy_zone_inventory_sha256": [digest],
        }
    )

    monkeypatch.setattr(
        "crypto_strategy_lab.feature_research.json.loads",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fast path must not parse inventory JSON")
        ),
    )
    zones, consumed = _sr_zone_inventory_frame(
        feature_context,
        strategy_interval="15m",
    )

    assert len(zones) == 1
    assert int(zones.loc[0, "zone_count"]) == 1
    assert zones.loc[0, "snapshot_sha256"] == digest
    assert {
        "sr_strategy_zone_inventory_json",
        "sr_strategy_zone_inventory_count",
        "sr_strategy_zone_inventory_sha256",
    } <= set(consumed)

    bad_count = feature_context.copy()
    bad_count.loc[0, "sr_strategy_zone_inventory_count"] = 2
    with pytest.raises(ResearchArtifactError, match="count/payload mismatch"):
        _sr_zone_inventory_frame(
            bad_count,
            strategy_interval="15m",
        )


def test_sr_snapshot_semantics_are_validated_before_persistence():
    valid = [
        {
            "zone_id": "SUPPORT:1",
            "structure": "SUPPORT",
            "zone_low": 95.0,
            "zone_high": 96.0,
            "source_count": 1,
            "test_count": 0,
            "nearest": True,
        }
    ]
    _validate_sr_zone_inventory(valid, inventory_column="sr_4h_zone_inventory_json")

    duplicate = valid + [dict(valid[0])]
    with pytest.raises(ResearchArtifactError, match="duplicate zone identity"):
        _validate_sr_zone_inventory(
            duplicate, inventory_column="sr_4h_zone_inventory_json"
        )

    multiple_nearest = [
        valid[0],
        {
            **valid[0],
            "zone_id": "SUPPORT:2",
        },
    ]
    with pytest.raises(ResearchArtifactError, match="multiple nearest"):
        _validate_sr_zone_inventory(
            multiple_nearest, inventory_column="sr_4h_zone_inventory_json"
        )



def test_writer_persists_compact_versioned_artifacts_and_queries_multiple_families(tmp_path):
    run = _write_run(tmp_path)
    research = run / "research"
    assert (research / "trades.parquet").is_file()
    assert (research / "feature_context.parquet").is_file()
    assert (research / "sr_zones.parquet").is_file()
    manifest = json.loads((research / "research_manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_contract"] == FEATURE_RESEARCH_ARTIFACT_CONTRACT
    assert manifest["artifact_version"] == 1
    assert manifest["trade_row_count"] == 5
    assert manifest["feature_context_row_count"] == 5
    assert manifest["sr_zone_row_count"] == 5
    assert manifest["sr_zone_expanded_row_count"] == 10
    assert manifest["sr_zone_storage_contract"] == "SNAPSHOT_JSON_V3"
    assert manifest["artifact_sizes_bytes"]["trades"] > 0
    assert manifest["artifact_sizes_bytes"]["feature_context"] > 0
    assert manifest["artifact_sizes_bytes"]["sr_zones"] > 0
    timings = manifest["artifact_stage_timings"]
    assert {
        "setup_and_trade_validation",
        "feature_context_build",
        "sr_snapshot_build",
        "artifact_frame_finalize",
        "write_trades_parquet",
        "write_feature_context_parquet",
        "write_sr_zones_parquet",
        "trade_fingerprint",
        "hash_trades_parquet",
        "hash_feature_context_parquet",
        "hash_sr_zones_parquet",
    } <= set(timings)
    assert all(float(value) >= 0.0 for value in timings.values())
    assert manifest["artifact_write_seconds"] >= sum(timings.values())
    assert {"open_interest", "funding_rate"} <= set(manifest["trade_context_parity_columns"])

    con = duckdb.connect()
    columns = {
        row[0]
        for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{research / 'feature_context.parquet'}')"
        ).fetchall()
    }
    con.close()
    assert "strategy_index" in columns
    assert "momentum_return_24h" in columns
    assert "sr_4h_zone_inventory_json" not in columns
    assert "open" not in columns and "high" not in columns and "low" not in columns
    assert "volume" not in columns

    con = duckdb.connect()
    zones = con.execute(
        f"SELECT * FROM read_parquet('{research / 'sr_zones.parquet'}') "
        "ORDER BY strategy_index"
    ).fetchdf()
    con.close()
    assert len(zones) == 5
    assert set(zones["sr_timeframe"]) == {"4h"}
    assert zones["zone_count"].eq(2).all()
    assert "zone_inventory_json" in zones.columns
    assert "snapshot_sha256" in zones.columns
    for _, snapshot in zones.iterrows():
        payload = snapshot["zone_inventory_json"]
        assert snapshot["snapshot_sha256"] == hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()
        inventory = json.loads(payload)
        assert len(inventory) == 2
        assert {zone["structure"] for zone in inventory} == {"SUPPORT"}
        assert sum(bool(zone["nearest"]) for zone in inventory) == 1
        assert {zone["zone_id"] for zone in inventory} == {"SUPPORT:0", "SUPPORT:1"}
    for column in (
        "strategy_candle_open_time",
        "decision_available_at",
        "sr_completed_candle_time",
    ):
        assert zones[column].dt.tz is None


    with ResearchQueryService(run) as service:
        grouped = service.query(
            {"dimensions": [{"column": "market_regime"}, {"column": "price_oi_state"}]}
        )
        assert grouped.trades.sum() == 5
        bull_up = grouped[
            (grouped.market_regime == "BULL") & (grouped.price_oi_state == "UP")
        ].iloc[0]
        assert (bull_up.trades, bull_up.wins, bull_up.losses, bull_up.breakeven) == (3, 1, 2, 0)
        assert bull_up.net_r == pytest.approx(-0.5)

        combined = service.query(
            {
                "dimensions": [
                    {"column": "mean_reversion_state"},
                    {"column": "funding_bias"},
                    {"column": "taker_imbalance"},
                    {"column": "trade_flow_delta"},
                    {"column": "book_depth_covered"},
                ]
            }
        )
        assert combined.trades.sum() == 5
        assert service.last_query_seconds is not None
        assert service.last_query_seconds >= 0


def test_duckdb_buckets_missing_filters_and_exact_signal_index_join(tmp_path, monkeypatch):
    run = _write_run(tmp_path)
    monkeypatch.setattr(
        pd, "read_parquet", lambda *args, **kwargs: pytest.fail("pandas.read_parquet used")
    )
    with ResearchQueryService(run) as service:
        buckets = service.query(
            {
                "dimensions": [
                    {
                        "column": "directional_di",
                        "alias": "di",
                        "boundaries": [0, 5, 10, 15, 20, 25, 30],
                    }
                ]
            }
        )
        assert set(buckets.di) == {"[0,5)", "[5,10)", "[10,15)", "[20,25)", "[30,+inf)"}
        assert buckets.trades.sum() == 5

        missing = service.query(
            {"dimensions": [{"column": "book_depth_imbalance"}]}
        )
        assert missing.trades.sum() == 5
        assert missing.loc[
            missing.book_depth_imbalance == "MISSING", "trades"
        ].item() == 1

        filtered = service.query(
            {
                "dimensions": [{"column": "price_oi_state"}],
                "filters": [{"column": "year", "operator": "=", "value": 2025}],
            }
        )
        assert filtered.trades.sum() == 5

    # Entry time is deliberately after the next candle begins; exact context still
    # comes from research_signal_index, never nearest-time reconstruction.
    con = duckdb.connect()
    trades_path = run / "research" / "trades.parquet"
    trades = con.execute(f"SELECT * FROM read_parquet('{trades_path}')").fetchdf()
    trades.loc[1, "entry_time"] = pd.Timestamp("2025-01-01T08:01:00Z")
    con.register("t", trades)
    con.execute(f"COPY t TO '{trades_path}' (FORMAT PARQUET, OVERWRITE 1)")
    con.close()
    _rehash(run, "trades", trades_path)
    manifest_path = run / "research" / "research_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Refresh the artifact fingerprint because entry time is an execution artifact
    # field; the join key itself must still remain signal index 1.
    from crypto_strategy_lab.feature_research import _trade_fingerprint
    con = duckdb.connect()
    manifest["trade_fingerprint"] = _trade_fingerprint(
        con.execute(f"SELECT * FROM read_parquet('{trades_path}')").fetchdf()
    )
    con.close()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with ResearchQueryService(run) as service:
        up = service.query(
            {
                "dimensions": [{"column": "open_interest"}],
                "filters": [{"column": "pair_id", "operator": "=", "value": 1}],
            }
        )
        assert up.open_interest.item() == "101.0"


def test_causal_and_research_value_mismatches_are_errors_after_hash_validation(tmp_path):
    run = _write_run(tmp_path)
    context_path = run / "research" / "feature_context.parquet"
    con = duckdb.connect()
    context = con.execute(f"SELECT * FROM read_parquet('{context_path}')").fetchdf()
    context.loc[1, "decision_available_at"] += pd.Timedelta(minutes=15)
    con.register("c", context)
    con.execute(f"COPY c TO '{context_path}' (FORMAT PARQUET, OVERWRITE 1)")
    con.close()
    _rehash(run, "feature_context", context_path)
    with pytest.raises(ResearchArtifactError, match="availability is invalid|timestamp mismatch"):
        ResearchQueryService(run)

    run = _write_run(tmp_path / "other")
    trades_path = run / "research" / "trades.parquet"
    con = duckdb.connect()
    trades = con.execute(f"SELECT * FROM read_parquet('{trades_path}')").fetchdf()
    trades.loc[1, "open_interest"] = 999
    con.register("t", trades)
    con.execute(f"COPY t TO '{trades_path}' (FORMAT PARQUET, OVERWRITE 1)")
    con.close()
    _rehash(run, "trades", trades_path)
    with pytest.raises(ResearchArtifactError, match="research-value mismatch"):
        ResearchQueryService(run)


def test_corrupt_artifact_missing_legacy_and_unavailable_column_are_explicit(tmp_path):
    with pytest.raises(ResearchArtifactError, match="does not contain Task-16"):
        ResearchQueryService(tmp_path)

    run = _write_run(tmp_path / "valid")
    with ResearchQueryService(run) as service:
        with pytest.raises(ResearchArtifactError, match="unavailable"):
            service.query({"dimensions": [{"column": "not_enabled"}]})

    path = run / "research" / "feature_context.parquet"
    path.write_bytes(path.read_bytes() + b"corrupt")
    with pytest.raises(ResearchArtifactError, match="hash mismatch"):
        ResearchQueryService(run)


def test_artifact_queries_need_no_raw_data_runner_or_pandas_parquet(tmp_path, monkeypatch):
    run = _write_run(tmp_path)

    import crypto_strategy_lab.data as data_module
    import crypto_strategy_lab.research_runner as runner_module

    monkeypatch.setattr(
        data_module,
        "MarketDataStore",
        lambda *args, **kwargs: pytest.fail("MarketDataStore must not be called"),
    )
    monkeypatch.setattr(
        runner_module.ResearchRunner,
        "run",
        lambda *args, **kwargs: pytest.fail("ResearchRunner must not be called"),
    )
    monkeypatch.setattr(
        pd, "read_parquet", lambda *args, **kwargs: pytest.fail("pandas.read_parquet used")
    )

    with ResearchQueryService(run) as service:
        for spec in (
            {"dimensions": [{"column": "market_regime"}]},
            {"dimensions": [{"column": "funding_bias"}]},
            {"dimensions": [{"column": "price_oi_state"}]},
        ):
            result = service.query(spec)
            assert result.trades.sum() == 5


def test_zero_trade_completed_run_is_still_queryable(tmp_path):
    run = _write_run(tmp_path, empty=True)
    with ResearchQueryService(run) as service:
        result = service.query({"dimensions": [{"column": "market_regime"}]})
        assert result.empty
        totals = service.query({})
        assert int(totals.trades.iloc[0]) == 0
