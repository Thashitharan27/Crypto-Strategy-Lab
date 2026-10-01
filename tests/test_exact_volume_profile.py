import json

import duckdb
import numpy as np
import pandas as pd

from crypto_strategy_lab.exact_volume_profile import (
    _parquet_payload_rows,
    _partition_time_ranges,
    exact_profile_frame,
)


def _aggregate(minutes=80):
    starts = pd.date_range("2026-01-01", periods=minutes, freq="1min", tz="UTC")
    payload = []
    for i, _ in enumerate(starts):
        price = 100.0 + 0.02 * i
        payload.append(json.dumps([[price, 2.0, 1.2, 0.8]], separators=(",", ":")))
    return pd.DataFrame({
        "period_start": starts,
        "period_end": starts + pd.Timedelta(minutes=1),
        "available_at": starts + pd.Timedelta(minutes=1),
        "volume_at_price_json": payload,
    })


def _strategy(minutes=80):
    starts = pd.date_range("2026-01-01", periods=minutes, freq="1min", tz="UTC")
    close = 100.0 + 0.02 * np.arange(minutes)
    return pd.DataFrame({
        "period_start": starts,
        "available_at": starts + pd.Timedelta(minutes=1),
        "open": close - 0.02,
        "high": close + 0.10,
        "low": close - 0.10,
        "close": close,
    })


def test_exact_aggtrade_profile_emits_strategy_context_after_warmup():
    out = exact_profile_frame(
        _aggregate(),
        _strategy(),
        strategy_minutes=1,
        atr_period=5,
        lookback_bars=20,
        bin_bps=5.0,
    )
    row = out.iloc[-1]
    assert row["vp_exact_strategy_position"] in {
        "ABOVE_VAH", "INSIDE_VALUE", "BELOW_VAL"
    }
    assert np.isfinite(row["vp_exact_strategy_poc_distance_atr"])
    assert np.isfinite(row["vp_exact_strategy_hvn_distance_atr"])
    assert 0.0 <= row["vp_exact_strategy_hvn_strength"] <= 1.0


def test_future_volume_at_price_cannot_change_past_profile():
    aggregate = _aggregate()
    strategy = _strategy()
    before = exact_profile_frame(
        aggregate,
        strategy,
        strategy_minutes=1,
        atr_period=5,
        lookback_bars=20,
        bin_bps=5.0,
    )

    changed = aggregate.copy()
    cutoff = 50
    changed.loc[cutoff:, "volume_at_price_json"] = json.dumps(
        [[500.0, 1_000_000.0, 1_000_000.0, 0.0]],
        separators=(",", ":"),
    )
    after = exact_profile_frame(
        changed,
        strategy,
        strategy_minutes=1,
        atr_period=5,
        lookback_bars=20,
        bin_bps=5.0,
    )

    columns = [
        "vp_exact_strategy_poc_distance_atr",
        "vp_exact_strategy_hvn_distance_atr",
        "vp_exact_strategy_hvn_strength",
        "vp_exact_strategy_accumulation_score",
    ]
    pd.testing.assert_frame_equal(
        before.loc[: cutoff - 1, columns],
        after.loc[: cutoff - 1, columns],
    )


def test_parquet_backed_profile_matches_inline_without_materializing_json(tmp_path):
    aggregate = _aggregate(minutes=180)
    strategy = _strategy(minutes=180)
    inline = exact_profile_frame(
        aggregate,
        strategy,
        strategy_minutes=1,
        atr_period=5,
        lookback_bars=20,
        bin_bps=5.0,
    )

    parquet = tmp_path / "trade_aggregate.parquet"
    with duckdb.connect() as con:
        con.register("aggregate_frame", aggregate)
        escaped = str(parquet).replace("'", "''")
        con.execute(
            f"COPY aggregate_frame TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )

    lazy = aggregate.drop(columns=["volume_at_price_json"]).copy()
    lazy.attrs["volume_at_price_parquet_paths"] = (str(parquet),)
    streamed = exact_profile_frame(
        lazy,
        strategy,
        strategy_minutes=1,
        atr_period=5,
        lookback_bars=20,
        bin_bps=5.0,
    )

    pd.testing.assert_frame_equal(inline, streamed)


def test_streamed_profile_uses_last_partition_for_overlap(tmp_path):
    base = _aggregate(minutes=80)
    strategy = _strategy(minutes=80)

    first = base.copy()
    second = base.copy()
    # Same minute timeline, but a conflicting exact-price payload in the later
    # partition. The aggregate loader resolves overlaps with keep="last", so the
    # streamed profile must use the second partition deterministically too.
    second.loc[20, "volume_at_price_json"] = json.dumps(
        [[250.0, 5000.0, 5000.0, 0.0]], separators=(",", ":")
    )

    paths = []
    for idx, frame in enumerate((first, second)):
        parquet = tmp_path / f"part-{idx}.parquet"
        with duckdb.connect() as con:
            con.register("aggregate_frame", frame)
            escaped = str(parquet).replace("'", "''")
            con.execute(
                f"COPY aggregate_frame TO '{escaped}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        paths.append(str(parquet))

    expected = base.copy()
    expected.loc[20, "volume_at_price_json"] = second.loc[
        20, "volume_at_price_json"
    ]
    expected_profile = exact_profile_frame(
        expected,
        strategy,
        strategy_minutes=1,
        atr_period=5,
        lookback_bars=20,
        bin_bps=5.0,
    )

    lazy = base.drop(columns=["volume_at_price_json"]).copy()
    lazy.attrs["volume_at_price_parquet_paths"] = tuple(paths)
    streamed = exact_profile_frame(
        lazy,
        strategy,
        strategy_minutes=1,
        atr_period=5,
        lookback_bars=20,
        bin_bps=5.0,
    )

    pd.testing.assert_frame_equal(expected_profile, streamed)


def test_streamed_profile_duplicate_resolution_uses_later_partition_with_arg_max(tmp_path):
    base = _aggregate(minutes=20)
    strategy = _strategy(minutes=20)

    first = base.copy()
    second = base.copy()
    second.loc[5, "volume_at_price_json"] = json.dumps(
        [[333.0, 1234.0, 1234.0, 0.0]], separators=(",", ":")
    )

    paths = []
    for idx, frame in enumerate((first, second)):
        parquet = tmp_path / f"argmax-{idx}.parquet"
        with duckdb.connect() as con:
            con.register("aggregate_frame", frame)
            escaped = str(parquet).replace("'", "''")
            con.execute(
                f"COPY aggregate_frame TO '{escaped}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        paths.append(str(parquet))

    expected = base.copy()
    expected.loc[5, "volume_at_price_json"] = second.loc[5, "volume_at_price_json"]
    expected_profile = exact_profile_frame(
        expected,
        strategy,
        strategy_minutes=1,
        atr_period=5,
        lookback_bars=10,
        bin_bps=5.0,
    )

    lazy = base.drop(columns=["volume_at_price_json"]).copy()
    lazy.attrs["volume_at_price_parquet_paths"] = tuple(paths)
    streamed = exact_profile_frame(
        lazy,
        strategy,
        strategy_minutes=1,
        atr_period=5,
        lookback_bars=10,
        bin_bps=5.0,
    )
    pd.testing.assert_frame_equal(expected_profile, streamed)


def test_parquet_payload_stream_chunks_multiweek_history_without_duplicates(tmp_path):
    starts = pd.date_range(
        "2026-01-01",
        periods=8 * 24 * 60,
        freq="1min",
        tz="UTC",
    )
    frame = pd.DataFrame(
        {
            "available_at": starts,
            "volume_at_price_json": [
                json.dumps([[100.0 + i * 0.001, 1.0]], separators=(",", ":"))
                for i in range(len(starts))
            ],
        }
    )
    parquet = tmp_path / "multiweek.parquet"
    with duckdb.connect() as con:
        con.register("payloads", frame)
        escaped = str(parquet).replace("'", "''")
        con.execute(
            f"COPY payloads TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )

    rows = list(
        _parquet_payload_rows(
            (str(parquet),),
            starts[0],
            starts[-1],
        )
    )
    assert len(rows) == len(frame)
    assert rows[0][0] == starts[0]
    assert rows[-1][0] == starts[-1]
    assert all(left[0] < right[0] for left, right in zip(rows, rows[1:]))


def test_streamed_profile_reads_partitions_sequentially_and_preserves_later_wins(tmp_path):
    starts = pd.date_range(
        "2026-01-01",
        periods=3 * 24 * 60,
        freq="1min",
        tz="UTC",
    )
    base = pd.DataFrame(
        {
            "available_at": starts,
            "volume_at_price_json": [
                json.dumps([[100.0 + i * 0.001, 1.0]], separators=(",", ":"))
                for i in range(len(starts))
            ],
        }
    )
    later = base.iloc[24 * 60 :].copy()
    conflict_time = starts[30 * 60]
    later.loc[
        later["available_at"].eq(conflict_time),
        "volume_at_price_json",
    ] = json.dumps([[777.0, 9.0]], separators=(",", ":"))

    paths = []
    for idx, frame in enumerate((base, later)):
        parquet = tmp_path / f"sequential-{idx}.parquet"
        with duckdb.connect() as con:
            con.register("payloads", frame)
            escaped = str(parquet).replace("'", "''")
            con.execute(
                f"COPY payloads TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        paths.append(str(parquet))

    rows = list(
        _parquet_payload_rows(
            tuple(paths),
            starts[0],
            starts[-1],
        )
    )
    assert len(rows) == len(base)
    assert all(left[0] < right[0] for left, right in zip(rows, rows[1:]))
    payload_by_time = dict(rows)
    assert payload_by_time[conflict_time] == json.dumps(
        [[777.0, 9.0]], separators=(",", ":")
    )


def test_partition_scan_order_does_not_matter_because_chunk_is_sorted_in_python(tmp_path):
    starts = pd.date_range(
        "2026-01-01",
        periods=180,
        freq="1min",
        tz="UTC",
    )
    shuffled = pd.DataFrame(
        {
            "available_at": starts[::-1],
            "volume_at_price_json": [
                json.dumps([[100.0 + i * 0.01, 1.0]], separators=(",", ":"))
                for i in range(len(starts))
            ],
        }
    )
    parquet = tmp_path / "unsorted.parquet"
    with duckdb.connect() as con:
        con.register("payloads", shuffled)
        escaped = str(parquet).replace("'", "''")
        con.execute(
            f"COPY payloads TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )

    rows = list(
        _parquet_payload_rows(
            (str(parquet),),
            starts[0],
            starts[-1],
        )
    )
    assert [row[0] for row in rows] == list(starts)


def test_partition_time_ranges_read_trade_aggregate_manifests(tmp_path):
    parquet = tmp_path / "part.parquet"
    parquet.write_bytes(b"placeholder")
    parquet.with_suffix(".json").write_text(
        json.dumps(
            {
                "source_period_start": "2026-01-01T00:00:00+00:00",
                "source_period_end": "2026-02-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    ranges = _partition_time_ranges((str(parquet),))
    assert len(ranges) == 1
    _, path, start, end = ranges[0]
    assert path == parquet
    assert start == pd.Timestamp("2026-01-01T00:00:00Z")
    assert end == pd.Timestamp("2026-02-01T00:00:00Z")


def test_payload_stream_skips_nonoverlapping_partitions(tmp_path, monkeypatch):
    jan_starts = pd.date_range("2026-01-01", periods=10, freq="1min", tz="UTC")
    feb_starts = pd.date_range("2026-02-01", periods=10, freq="1min", tz="UTC")
    paths = []
    for idx, (starts, begin, finish) in enumerate(
        (
            (jan_starts, "2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"),
            (feb_starts, "2026-02-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00"),
        )
    ):
        frame = pd.DataFrame(
            {
                "available_at": starts,
                "volume_at_price_json": [
                    json.dumps([[100.0 + i, 1.0]], separators=(",", ":"))
                    for i in range(len(starts))
                ],
            }
        )
        parquet = tmp_path / f"part-{idx}.parquet"
        with duckdb.connect() as con:
            con.register("payloads", frame)
            escaped = str(parquet).replace("'", "''")
            con.execute(
                f"COPY payloads TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        parquet.with_suffix(".json").write_text(
            json.dumps(
                {
                    "source_period_start": begin,
                    "source_period_end": finish,
                }
            ),
            encoding="utf-8",
        )
        paths.append(str(parquet))

    rows = list(
        _parquet_payload_rows(
            tuple(paths),
            jan_starts[0],
            jan_starts[-1],
        )
    )
    assert len(rows) == len(jan_starts)
    assert rows[0][0] == jan_starts[0]
    assert rows[-1][0] == jan_starts[-1]


def test_shared_exact_profile_cache_reuses_completed_build_without_source_rescan(tmp_path):
    aggregate = _aggregate(minutes=180)
    strategy = _strategy(minutes=180)
    parquet = tmp_path / "trade-aggregate.parquet"
    with duckdb.connect() as con:
        con.register("aggregate_frame", aggregate)
        escaped = str(parquet).replace("'", "''")
        con.execute(
            f"COPY aggregate_frame TO '{escaped}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    parquet.with_suffix(".json").write_text(
        json.dumps(
            {
                "aggregate_schema_version": 1,
                "source_fingerprint": "immutable-aggtrade-source",
                "source_period_start": "2026-01-01T00:00:00+00:00",
                "source_period_end": "2026-01-02T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    def lazy_source():
        frame = aggregate.drop(columns=["volume_at_price_json"]).copy()
        frame.attrs["volume_at_price_parquet_paths"] = (str(parquet),)
        frame.attrs["exact_volume_profile_cache_root"] = str(tmp_path / "cache")
        frame.attrs["exact_volume_profile_cache_scope"] = {
            "exchange": "binance",
            "market": "futures_um",
            "symbol": "BTCUSDT",
            "strategy_interval": "1m",
        }
        frame.attrs[
            "exact_volume_profile_strategy_source_identity"
        ] = "immutable-kline-source"
        return frame

    first = exact_profile_frame(
        lazy_source(),
        strategy,
        strategy_minutes=1,
        atr_period=5,
        lookback_bars=20,
        bin_bps=5.0,
    )
    assert first.attrs["exact_volume_profile_cache_hit"] is False
    cache_key = first.attrs["exact_volume_profile_cache_key"]

    # The second call must come from the shared derived cache rather than
    # reopening the expensive source Parquet. The immutable manifest remains
    # available so source provenance can still be verified.
    parquet.unlink()
    second = exact_profile_frame(
        lazy_source(),
        strategy,
        strategy_minutes=1,
        atr_period=5,
        lookback_bars=20,
        bin_bps=5.0,
    )
    assert second.attrs["exact_volume_profile_cache_hit"] is True
    assert second.attrs["exact_volume_profile_cache_key"] == cache_key
    pd.testing.assert_frame_equal(
        first.reset_index(drop=True),
        second.reset_index(drop=True),
        check_dtype=False,
    )
