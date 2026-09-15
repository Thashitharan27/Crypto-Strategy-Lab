from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import crypto_strategy_lab.ai_batch as batch_module
from crypto_strategy_lab.ai_batch import (
    BATCH_ENDPOINT,
    batch_request_row,
    collect_batch_to_cache,
    extract_response_output_text,
    prepare_engine_batches,
)
from crypto_strategy_lab.ai_decision import AIDecisionCache
from crypto_strategy_lab.ai_snapshot_enrichment import enrich_ai_snapshot


class _Engine:
    signal_strategy_mode = "OPENAI_DECISION"
    times = np.arange(3)
    risk = np.ones(3)
    config = SimpleNamespace(
        enable_daily_entry_schedule=False,
        entry_mode="WAIT_UNTIL_CLOSED",
        entry_interval=1,
    )

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path

    def _in_trading_window(self, _i):
        return True

    def _regime_at(self, _i):
        return "BULL"

    def _ai_runtime_identity(self):
        return "gpt-5.6-sol", "medium", "direction_v1", "CACHE_ONLY", self.cache_path

    def _ai_market_snapshot(self, i):
        return {
            "snapshot_version": 1,
            "decision_timestamp": f"2026-01-01T00:{i:02d}:00+00:00",
            "symbol": "BTCUSDT",
            "strategy_timeframe_minutes": 15,
            "market_regime": "BULL",
            "price": {"close": 100 + i},
        }


def test_prepare_splits_at_request_limit_and_never_needs_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    engine = _Engine(tmp_path / "cache.jsonl")
    prepared = prepare_engine_batches(engine, tmp_path / "batch", max_requests=2)

    assert prepared.candidate_count == 3
    assert prepared.prepared_count == 3
    assert prepared.skipped_cached == 0
    assert [item.request_count for item in prepared.files] == [2, 1]

    first = json.loads(prepared.files[0].request_file.read_text(encoding="utf-8").splitlines()[0])
    assert first["method"] == "POST"
    assert first["url"] == BATCH_ENDPOINT
    assert first["body"]["model"] == "gpt-5.6-sol"
    assert first["body"]["reasoning"] == {"effort": "medium"}
    assert first["body"]["text"]["format"]["type"] == "json_schema"


def test_prepare_skips_existing_cache_decision(tmp_path):
    engine = _Engine(tmp_path / "cache.jsonl")
    snapshot = engine._ai_market_snapshot(0)
    request, manifest = batch_request_row(
        snapshot,
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        prompt_version="direction_v1",
    )
    del request
    cache = AIDecisionCache(engine.cache_path)
    from crypto_strategy_lab.ai_decision import validate_ai_decision

    decision = validate_ai_decision(
        {
            "long_confidence": 61,
            "short_confidence": 39,
            "selected_side": "LONG",
            "conflict_level": "MODERATE",
            "key_long_factors": ["trend"],
            "key_short_factors": ["resistance"],
            "summary": "Long is modestly stronger.",
        },
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        prompt_version="direction_v1",
        snapshot_hash=manifest["snapshot_hash"],
        response_id="resp_cached",
    )
    cache.put(manifest["cache_key"], decision)

    prepared = prepare_engine_batches(engine, tmp_path / "batch")
    assert prepared.candidate_count == 3
    assert prepared.prepared_count == 2
    assert prepared.skipped_cached == 1


def test_enrichment_strips_market_permission_hints():
    class Config:
        market_symbol = "BTCUSDT"
        input_csv = ""

    class Engine:
        config = Config()

    base = {
        "directional_context": {
            "LONG": {"trade_contract": {"enabled": True, "timeout_minutes": 60}},
            "SHORT": {"trade_contract": {"enabled": False, "timeout_minutes": 60}},
        }
    }
    enriched = enrich_ai_snapshot(Engine(), 0, base)
    assert "enabled" not in enriched["directional_context"]["LONG"]["trade_contract"]
    assert "enabled" not in enriched["directional_context"]["SHORT"]["trade_contract"]
    assert enriched["directional_context"]["LONG"]["trade_contract"]["timeout_minutes"] == 60


def test_extract_responses_api_structured_output():
    text = extract_response_output_text(
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": '{"selected_side":"LONG"}'}
                    ],
                }
            ]
        }
    )
    assert text == '{"selected_side":"LONG"}'


def test_collect_maps_out_of_order_custom_ids_into_cache(tmp_path, monkeypatch):
    snapshot_a = {
        "decision_timestamp": "2026-01-01T00:00:00+00:00",
        "symbol": "BTCUSDT",
    }
    snapshot_b = {
        "decision_timestamp": "2026-01-01T00:15:00+00:00",
        "symbol": "BTCUSDT",
    }
    _request_a, manifest_a = batch_request_row(
        snapshot_a,
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        prompt_version="direction_v1",
    )
    _request_b, manifest_b = batch_request_row(
        snapshot_b,
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        prompt_version="direction_v1",
    )
    manifest_path = tmp_path / "manifest.jsonl"
    manifest_path.write_text(
        "\n".join(json.dumps(row) for row in (manifest_a, manifest_b)) + "\n",
        encoding="utf-8",
    )

    def output_row(meta, side, long_score):
        raw = {
            "long_confidence": long_score,
            "short_confidence": 100 - long_score,
            "selected_side": side,
            "conflict_level": "LOW",
            "key_long_factors": ["trend"],
            "key_short_factors": ["countertrend"],
            "summary": f"{side} is stronger.",
        }
        return {
            "custom_id": meta["custom_id"],
            "response": {
                "status_code": 200,
                "body": {
                    "id": f"resp-{meta['custom_id'][-8:]}",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": json.dumps(raw)}
                            ],
                        }
                    ],
                },
            },
            "error": None,
        }

    output = "\n".join(
        json.dumps(row)
        for row in (
            output_row(manifest_b, "SHORT", 35),
            output_row(manifest_a, "LONG", 65),
        )
    ) + "\n"

    class Files:
        def content(self, file_id):
            assert file_id == "file-output"
            return SimpleNamespace(text=output)

    class Batches:
        def retrieve(self, batch_id):
            assert batch_id == "batch-123"
            return SimpleNamespace(
                id=batch_id,
                status="completed",
                output_file_id="file-output",
                error_file_id=None,
            )

    fake_client = SimpleNamespace(files=Files(), batches=Batches())
    monkeypatch.setattr(batch_module, "_openai_client", lambda: fake_client)

    cache_path = tmp_path / "cache.jsonl"
    result = collect_batch_to_cache("batch-123", manifest_path, cache_path)
    assert result["imported"] == 2
    assert result["failed"] == 0

    cache = AIDecisionCache(cache_path)
    a = cache.get(
        manifest_a["cache_key"],
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        prompt_version="direction_v1",
        expected_snapshot_hash=manifest_a["snapshot_hash"],
    )
    b = cache.get(
        manifest_b["cache_key"],
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        prompt_version="direction_v1",
        expected_snapshot_hash=manifest_b["snapshot_hash"],
    )
    assert a.selected_side == "LONG"
    assert b.selected_side == "SHORT"
