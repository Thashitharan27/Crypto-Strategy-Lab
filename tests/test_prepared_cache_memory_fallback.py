"""Prepared L3 cache exhaustion must not block valid simulations."""

import duckdb
import pytest

from crypto_strategy_lab.prepared_backtest import PreparedBacktestFrame
from crypto_strategy_lab.prepared_cache import (
    PREPARED_CACHE_STORE_MEMORY_LIMIT,
    PREPARED_CACHE_STORE_ROW_GROUP_SIZE,
    PreparedRunCache,
)


def test_memory_bounded_cache_writer_defaults():
    assert PREPARED_CACHE_STORE_MEMORY_LIMIT == "1GB"
    assert PREPARED_CACHE_STORE_ROW_GROUP_SIZE == 2048


def test_prepared_cache_store_oom_falls_back_to_uncached_frame(tmp_path, monkeypatch):
    cache = PreparedRunCache(tmp_path)
    frame = object.__new__(PreparedBacktestFrame)
    monkeypatch.setattr(cache, "load", lambda key: None)

    def fail_store(key, prepared, *, provenance):
        parquet, manifest = cache.paths(key)
        parquet.parent.mkdir(parents=True, exist_ok=True)
        parquet.with_suffix(".tmp.parquet").write_bytes(b"partial")
        manifest.with_suffix(".tmp.json").write_text("partial")
        raise duckdb.OutOfMemoryException("failed to pin block")

    monkeypatch.setattr(cache, "store", fail_store)
    with pytest.warns(RuntimeWarning, match="cache write skipped"):
        result, hit = cache.get_or_build(
            "oom-case", lambda: frame, provenance={}
        )
    assert result is frame
    assert hit is False
    parquet, manifest = cache.paths("oom-case")
    assert not parquet.with_suffix(".tmp.parquet").exists()
    assert not manifest.with_suffix(".tmp.json").exists()


def test_prepared_cache_other_write_errors_still_fail(tmp_path, monkeypatch):
    cache = PreparedRunCache(tmp_path)
    monkeypatch.setattr(cache, "load", lambda key: None)
    frame = object.__new__(PreparedBacktestFrame)

    def fail_store(key, prepared, *, provenance):
        raise ValueError("bad cache contract")

    monkeypatch.setattr(cache, "store", fail_store)
    with pytest.raises(ValueError, match="bad cache contract"):
        cache.get_or_build("bad-case", lambda: frame, provenance={})
