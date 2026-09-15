"""Causal OpenAI LONG/SHORT decision support for the strategy runtime.

The model is deliberately limited to direction selection. Existing strategy
permissions, Entry/Veto/Flip rules, sizing, stops, targets, fees and execution
remain deterministic and are applied by the mature simulator after the model
chooses a side.

Historical decisions are cached by a stable hash of the complete causal market
snapshot plus model/prompt identity. The default runtime mode is CACHE_ONLY so a
large backtest can never create API spend merely because an API key exists.
Set ``CRYPTO_STRATEGY_AI_MODE=CACHE_THEN_API`` explicitly when generating new
historical decisions or using the same path for a live decision point.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from crypto_strategy_lab.strategy_profiles import profile_key


OPENAI_DECISION_MODE = "OPENAI_DECISION"
AI_MODEL = "gpt-5.6-sol"
AI_REASONING_EFFORT = "medium"
AI_PROMPT_VERSION = "direction_v1"
AI_SNAPSHOT_VERSION = 1
AI_RECENT_BARS = 12
AI_CACHE_MODE_ENV = "CRYPTO_STRATEGY_AI_MODE"
AI_CACHE_PATH_ENV = "CRYPTO_STRATEGY_AI_CACHE"
AI_MODEL_ENV = "CRYPTO_STRATEGY_AI_MODEL"
AI_REASONING_ENV = "CRYPTO_STRATEGY_AI_REASONING_EFFORT"
AI_CACHE_ONLY = "CACHE_ONLY"
AI_CACHE_THEN_API = "CACHE_THEN_API"
AI_CACHE_MODES = (AI_CACHE_ONLY, AI_CACHE_THEN_API)

AI_DECISION_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "long_confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "short_confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "selected_side": {"type": "string", "enum": ["LONG", "SHORT"]},
        "conflict_level": {
            "type": "string",
            "enum": ["LOW", "MODERATE", "HIGH"],
        },
        "key_long_factors": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
        },
        "key_short_factors": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
        },
        "summary": {"type": "string", "maxLength": 600},
    },
    "required": [
        "long_confidence",
        "short_confidence",
        "selected_side",
        "conflict_level",
        "key_long_factors",
        "key_short_factors",
        "summary",
    ],
}

AI_SYSTEM_PROMPT = """You are the directional decision component of a causal crypto backtester.

Evaluate LONG and SHORT independently from only the supplied snapshot. Never use
future information and never invent unavailable evidence. The snapshot may show
conflicting evidence; weigh trend, market structure, momentum, mean reversion,
flow, positioning, and multi-timeframe support/resistance together.

You MUST choose LONG or SHORT. There is no abstain/no-trade option. Return integer
LONG and SHORT confidence scores that sum to exactly 100 and never return a
50/50 tie. A close case should be expressed as 51/49 rather than refusing to
choose. These are relative directional preference scores, not guaranteed market
probabilities.

The LONG and SHORT trade contracts can differ. Judge the side for the exact
contract shown, including stop/target and timeout behavior. Keep factor strings
short and evidence-based. conflict_level describes how strongly the evidence
families disagree; it never changes the requirement to choose a side.
"""


@dataclass(frozen=True)
class AIDirectionalDecision:
    long_confidence: int
    short_confidence: int
    selected_side: str
    conflict_level: str
    key_long_factors: tuple[str, ...]
    key_short_factors: tuple[str, ...]
    summary: str
    model: str = AI_MODEL
    reasoning_effort: str = AI_REASONING_EFFORT
    prompt_version: str = AI_PROMPT_VERSION
    snapshot_hash: str = ""
    response_id: str = ""
    cache_hit: bool = False

    @property
    def selected_confidence(self) -> int:
        return max(self.long_confidence, self.short_confidence)

    @property
    def decision_strength(self) -> int:
        return abs(self.long_confidence - self.short_confidence)

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["key_long_factors"] = list(self.key_long_factors)
        value["key_short_factors"] = list(self.key_short_factors)
        value["selected_confidence"] = self.selected_confidence
        value["decision_strength"] = self.decision_strength
        return value


def _factor_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be an array")
    result = tuple(str(item).strip() for item in value if str(item).strip())
    if len(result) > 8:
        raise ValueError(f"{field} cannot contain more than 8 factors")
    return result


def validate_ai_decision(
    raw: dict[str, Any],
    *,
    model: str = AI_MODEL,
    reasoning_effort: str = AI_REASONING_EFFORT,
    prompt_version: str = AI_PROMPT_VERSION,
    snapshot_hash: str = "",
    response_id: str = "",
    cache_hit: bool = False,
) -> AIDirectionalDecision:
    """Validate model output and derive the deterministic confidence gap."""
    if not isinstance(raw, dict):
        raise ValueError("AI decision must be a JSON object")
    try:
        long_score = int(raw["long_confidence"])
        short_score = int(raw["short_confidence"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("AI confidence scores must be integers") from exc
    if isinstance(raw.get("long_confidence"), bool) or isinstance(
        raw.get("short_confidence"), bool
    ):
        raise ValueError("AI confidence scores cannot be booleans")
    if not 0 <= long_score <= 100 or not 0 <= short_score <= 100:
        raise ValueError("AI confidence scores must be between 0 and 100")
    if long_score + short_score != 100:
        raise ValueError("AI LONG and SHORT confidence scores must total 100")
    if long_score == short_score:
        raise ValueError("AI decision cannot be a 50/50 tie")

    side = str(raw.get("selected_side", "")).upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("AI selected_side must be LONG or SHORT")
    expected = "LONG" if long_score > short_score else "SHORT"
    if side != expected:
        raise ValueError("AI selected_side must match the higher confidence score")

    conflict = str(raw.get("conflict_level", "")).upper()
    if conflict not in {"LOW", "MODERATE", "HIGH"}:
        raise ValueError("AI conflict_level must be LOW, MODERATE or HIGH")

    summary = str(raw.get("summary", "")).strip()
    if not summary:
        raise ValueError("AI decision summary cannot be empty")
    if len(summary) > 600:
        raise ValueError("AI decision summary cannot exceed 600 characters")

    return AIDirectionalDecision(
        long_confidence=long_score,
        short_confidence=short_score,
        selected_side=side,
        conflict_level=conflict,
        key_long_factors=_factor_tuple(raw.get("key_long_factors"), "key_long_factors"),
        key_short_factors=_factor_tuple(raw.get("key_short_factors"), "key_short_factors"),
        summary=summary,
        model=str(model),
        reasoning_effort=str(reasoning_effort),
        prompt_version=str(prompt_version),
        snapshot_hash=str(snapshot_hash),
        response_id=str(response_id or ""),
        cache_hit=bool(cache_hit),
    )


def _json_safe(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        else:
            stamp = stamp.tz_convert("UTC")
        return stamp.isoformat()
    if hasattr(value, "value") and not isinstance(value, str):
        return _json_safe(value.value)
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and missing:
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def canonical_snapshot(snapshot: dict[str, Any]) -> str:
    return json.dumps(
        _json_safe(snapshot), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_snapshot(snapshot).encode("utf-8")).hexdigest()


def decision_cache_key(
    snapshot: dict[str, Any], *, model: str, reasoning_effort: str, prompt_version: str
) -> tuple[str, str]:
    digest = snapshot_hash(snapshot)
    identity = {
        "snapshot_hash": digest,
        "model": str(model),
        "reasoning_effort": str(reasoning_effort),
        "prompt_version": str(prompt_version),
    }
    key = hashlib.sha256(canonical_snapshot(identity).encode("utf-8")).hexdigest()
    return key, digest


class AIDecisionCache:
    """Append-only JSONL cache. Last duplicate key wins on load."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._rows: dict[str, dict[str, Any]] | None = None

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._rows is not None:
            return self._rows
        rows: dict[str, dict[str, Any]] = {}
        if self.path.is_file():
            for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid AI decision cache JSON at {self.path}:{number}"
                    ) from exc
                key = str(row.get("cache_key", ""))
                if not key:
                    raise ValueError(
                        f"AI decision cache row {number} has no cache_key"
                    )
                rows[key] = row
        self._rows = rows
        return rows

    def get(
        self,
        key: str,
        *,
        model: str,
        reasoning_effort: str,
        prompt_version: str,
        expected_snapshot_hash: str,
    ) -> AIDirectionalDecision | None:
        row = self._load().get(key)
        if row is None:
            return None
        if str(row.get("snapshot_hash", "")) != expected_snapshot_hash:
            raise ValueError("AI decision cache hash mismatch")
        return validate_ai_decision(
            row.get("decision", {}),
            model=model,
            reasoning_effort=reasoning_effort,
            prompt_version=prompt_version,
            snapshot_hash=expected_snapshot_hash,
            response_id=str(row.get("response_id", "")),
            cache_hit=True,
        )

    def put(self, key: str, decision: AIDirectionalDecision) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "cache_key": key,
            "snapshot_hash": decision.snapshot_hash,
            "model": decision.model,
            "reasoning_effort": decision.reasoning_effort,
            "prompt_version": decision.prompt_version,
            "response_id": decision.response_id,
            "decision": {
                "long_confidence": decision.long_confidence,
                "short_confidence": decision.short_confidence,
                "selected_side": decision.selected_side,
                "conflict_level": decision.conflict_level,
                "key_long_factors": list(decision.key_long_factors),
                "key_short_factors": list(decision.key_short_factors),
                "summary": decision.summary,
            },
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
        self._load()[key] = row


class OpenAIDecisionClient:
    def __init__(
        self,
        *,
        model: str = AI_MODEL,
        reasoning_effort: str = AI_REASONING_EFFORT,
        prompt_version: str = AI_PROMPT_VERSION,
    ):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.prompt_version = prompt_version

    def decide(self, snapshot: dict[str, Any], *, snapshot_digest: str) -> AIDirectionalDecision:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY is required to generate an uncached AI decision"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The OpenAI Python SDK is required for AI decision generation"
            ) from exc

        client = OpenAI()
        response = client.responses.create(
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            instructions=AI_SYSTEM_PROMPT,
            input=canonical_snapshot(snapshot),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "crypto_direction_decision",
                    "schema": AI_DECISION_JSON_SCHEMA,
                    "strict": True,
                }
            },
        )
        output_text = str(getattr(response, "output_text", "") or "").strip()
        if not output_text:
            raise RuntimeError("OpenAI returned no structured direction output")
        try:
            raw = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenAI direction output was not valid JSON") from exc
        return validate_ai_decision(
            raw,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            prompt_version=self.prompt_version,
            snapshot_hash=snapshot_digest,
            response_id=str(getattr(response, "id", "") or ""),
            cache_hit=False,
        )


class OpenAIDecisionMixin:
    """Intercept only OPENAI_DECISION; all other signal strategies use super()."""

    def _infer_signal_strategy_mode(self):
        for profile in self.config.strategy_profiles.values():
            for rule in getattr(profile, "entry_rules", ()):
                mode = str(rule.get("_strategy_direction_mode", "")).upper()
                if mode == OPENAI_DECISION_MODE:
                    return OPENAI_DECISION_MODE
        return super()._infer_signal_strategy_mode()

    def _selected_direction(self, i):
        if getattr(self, "signal_strategy_mode", "DI") != OPENAI_DECISION_MODE:
            return super()._selected_direction(i)
        return self._ai_direction_decision(i).selected_side

    @staticmethod
    def _safe_array_value(values, i):
        try:
            return _json_safe(values[i])
        except (AttributeError, IndexError, KeyError, TypeError):
            return None

    def _ai_profile(self, regime: str, side: str):
        try:
            return self.config.strategy_profiles[profile_key(regime, side)]
        except (KeyError, TypeError):
            return None

    def _ai_trade_contract(self, regime: str, side: str) -> dict[str, Any]:
        profile = self._ai_profile(regime, side)
        if profile is None:
            return {"enabled": False}
        fields = (
            "enabled",
            "reward_risk_ratio",
            "risk_multiplier",
            "stop_loss_multiple",
            "partial_stop_enabled",
            "sl1_r",
            "sl1_close_pct",
            "sl2_r",
            "partial_profit_enabled",
            "tp1_r",
            "tp1_close_pct",
            "tp2_r",
            "trailing_enabled",
            "trailing_activation_r",
            "trailing_distance_r",
            "break_even_enabled",
            "break_even_activation_r",
            "break_even_offset_r",
            "timeout_enabled",
            "timeout_minutes",
            "r_step_trailing_enabled",
            "r_step_activation_r",
            "r_step_distance_r",
            "r_step_size_r",
            "r_step_maximum_r",
        )
        result = {field: _json_safe(getattr(profile, field, None)) for field in fields}
        result.update(
            risk_mode=_json_safe(getattr(self.config, "risk_mode", None)),
            atr_multiplier=_json_safe(getattr(self.config, "atr_multiplier", None)),
            risk_per_leg=_json_safe(getattr(self.config, "risk_per_leg", None)),
            entry_timing_mode=_json_safe(getattr(self.config, "entry_timing_mode", None)),
        )
        return result

    def _ai_sr_snapshot(self, i: int, side: str) -> dict[str, Any] | None:
        try:
            context = self._analyze_support_resistance(i, side)
        except Exception:
            return None
        if context is None:
            return None
        fields = (
            "near_support",
            "near_resistance",
            "inside_support_zone",
            "inside_resistance_zone",
            "support_state",
            "resistance_state",
            "support_held",
            "resistance_held",
            "trade_location_rating",
            "room_in_direction_atr",
            "nearest_support_distance_atr",
            "nearest_resistance_distance_atr",
            "support_rejection_atr",
            "resistance_rejection_atr",
            "support_test_count",
            "resistance_test_count",
            "bars_since_support_test",
            "bars_since_resistance_test",
        )
        return {field: _json_safe(getattr(context, field, None)) for field in fields}

    def _ai_pressure_snapshot(self, i: int, side: str) -> dict[str, Any]:
        try:
            raw = self._di_pressure_snapshot(i, side)
        except Exception:
            raw = {}
        fields = (
            "directional_di",
            "opposing_di",
            "plus_di_change",
            "minus_di_change",
            "directional_di_change",
            "opposing_di_change",
            "di_spread",
            "di_spread_change",
            "di_pressure_state",
            "di_pressure_lookback",
        )
        return {field: _json_safe(raw.get(field)) for field in fields}

    def _ai_research_value(self, i: int, feature: str, column: str):
        reader = getattr(self, "_prepared_research_raw_value", None)
        if reader is None:
            return None
        try:
            return _json_safe(reader(i, feature, column))
        except Exception:
            return None

    def _ai_futures_snapshot(self, i: int) -> dict[str, Any]:
        specs = {
            "oi_change_pct_5m": ("futures_positioning", "oi_change_pct_5m"),
            "oi_change_pct_1h": ("futures_positioning", "oi_change_pct_1h"),
            "oi_change_pct_24h": ("futures_positioning", "oi_change_pct_24h"),
            "oi_zscore_7d": ("futures_positioning", "oi_zscore_7d"),
            "price_change_pct_1h": ("futures_positioning", "price_change_pct_1h"),
            "price_oi_state": ("futures_positioning", "price_oi_state"),
            "oi_vs_price_state_1h": ("futures_positioning", "oi_vs_price_state_1h"),
            "top_trader_account_bias": ("futures_positioning", "top_trader_account_bias"),
            "top_trader_position_bias": ("futures_positioning", "top_trader_position_bias"),
            "global_long_short_account_bias": ("futures_positioning", "global_long_short_account_bias"),
            "taker_long_short_volume_bias": ("futures_positioning", "taker_long_short_volume_bias"),
            "funding_rate_bps": ("funding_context", "funding_rate_bps"),
            "funding_24h_sum_bps": ("funding_context", "funding_24h_sum_bps"),
            "funding_7d_zscore": ("funding_context", "funding_7d_zscore"),
            "funding_bias": ("funding_context", "funding_bias"),
            "mark_index_basis_bps": ("basis_context", "mark_index_basis_bps"),
            "mark_index_basis_state": ("basis_context", "mark_index_basis_state"),
            "mark_index_basis_zscore_7d": ("basis_context", "mark_index_basis_zscore_7d"),
            "premium_index_zscore_7d": ("basis_context", "premium_index_zscore_7d"),
            "taker_buy_sell_ratio": ("taker_flow_context", "taker_buy_sell_ratio"),
            "taker_delta_pct": ("taker_flow_context", "taker_delta_pct"),
            "taker_delta_pct_15m": ("taker_flow_context", "taker_delta_pct_15m"),
            "taker_delta_pct_1h": ("taker_flow_context", "taker_delta_pct_1h"),
            "taker_flow_persistence": ("taker_flow_context", "flow_persistence"),
        }
        return {
            name: self._ai_research_value(i, feature, column)
            for name, (feature, column) in specs.items()
        }

    def _ai_market_snapshot(self, i: int) -> dict[str, Any]:
        regime = str(self.market_regime_values[i]).upper()
        timestamp = pd.Timestamp(self.times[i])
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")

        start = max(0, i - AI_RECENT_BARS + 1)
        recent_bars = [
            {
                "timestamp": self.times[j],
                "open": self.open[j],
                "high": self.high[j],
                "low": self.low[j],
                "close": self.close[j],
                "volume": self.volume[j],
            }
            for j in range(start, i + 1)
        ]

        mr_fields = (
            "mean_reversion_distance_atr",
            "mean_reversion_distance_change_atr",
            "mean_reversion_state",
            "mean_reversion_motion",
            "mean_reversion_strength_label",
            "mean_reversion_bb_zscore",
            "mean_reversion_bb_location",
            "mean_reversion_signal",
        )
        mr = {
            field: self._safe_array_value(getattr(self, field, ()), i)
            for field in mr_fields
        }

        long_profile = self._ai_profile(regime, "LONG")
        short_profile = self._ai_profile(regime, "SHORT")
        rsi_periods = sorted(
            {
                int(getattr(profile, "rsi_period", 14))
                for profile in (long_profile, short_profile)
                if profile is not None
            }
        )
        rsi_values = {
            str(period): self._safe_array_value(
                getattr(self, "profile_rsi_values", {}).get(period, ()), i
            )
            for period in rsi_periods
        }

        snapshot = {
            "snapshot_version": AI_SNAPSHOT_VERSION,
            "decision_timestamp": timestamp,
            "strategy_timeframe_minutes": getattr(
                self.config, "strategy_timeframe_minutes", None
            ),
            "market_regime": regime,
            "price": {
                "open": self.open[i],
                "high": self.high[i],
                "low": self.low[i],
                "close": self.close[i],
                "volume": self.volume[i],
            },
            "recent_completed_bars": recent_bars,
            "indicators": {
                "atr": self._safe_array_value(self.atr_values, i),
                "atr_pct": self._safe_array_value(getattr(self, "atr_pct_values", ()), i),
                "adx": self._safe_array_value(self.adx_values, i),
                "plus_di": self._safe_array_value(self.plus_di_values, i),
                "minus_di": self._safe_array_value(self.minus_di_values, i),
                "di_spread": self._safe_array_value(self.di_spread, i),
                "rsi_by_period": rsi_values,
                "ema_50": self._safe_array_value(getattr(self, "ema_50_values", ()), i),
                "ema_100": self._safe_array_value(getattr(self, "ema_100_values", ()), i),
                "ema_200": self._safe_array_value(getattr(self, "ema_200_values", ()), i),
                "macd_line": self._safe_array_value(getattr(self, "macd_line_values", ()), i),
                "macd_signal": self._safe_array_value(getattr(self, "macd_signal_values", ()), i),
                "macd_histogram": self._safe_array_value(getattr(self, "macd_histogram_values", ()), i),
                "macd_histogram_change": self._safe_array_value(
                    getattr(self, "macd_histogram_change_values", ()), i
                ),
                "close_location": self._safe_array_value(
                    getattr(self, "close_location_values", ()), i
                ),
                "mean_reversion": mr,
            },
            "directional_context": {
                side: {
                    "di_pressure": self._ai_pressure_snapshot(i, side),
                    "support_resistance": self._ai_sr_snapshot(i, side),
                    "trade_contract": self._ai_trade_contract(regime, side),
                }
                for side in ("LONG", "SHORT")
            },
            "futures_context": self._ai_futures_snapshot(i),
        }
        return _json_safe(snapshot)

    def _ai_runtime_identity(self) -> tuple[str, str, str, str, Path]:
        model = str(os.environ.get(AI_MODEL_ENV, AI_MODEL)).strip() or AI_MODEL
        reasoning = (
            str(os.environ.get(AI_REASONING_ENV, AI_REASONING_EFFORT)).strip().lower()
            or AI_REASONING_EFFORT
        )
        mode = str(os.environ.get(AI_CACHE_MODE_ENV, AI_CACHE_ONLY)).strip().upper()
        if mode not in AI_CACHE_MODES:
            raise ValueError(
                f"{AI_CACHE_MODE_ENV} must be one of: {', '.join(AI_CACHE_MODES)}"
            )
        cache_path = Path(
            os.environ.get(AI_CACHE_PATH_ENV, "output/ai_decision_cache.jsonl")
        )
        return model, reasoning, AI_PROMPT_VERSION, mode, cache_path

    def _ai_direction_decision(self, i: int) -> AIDirectionalDecision:
        if not hasattr(self, "_ai_decisions_by_index"):
            self._ai_decisions_by_index = {}
        existing = self._ai_decisions_by_index.get(int(i))
        if existing is not None:
            return existing

        snapshot = self._ai_market_snapshot(i)
        model, reasoning, prompt_version, mode, cache_path = self._ai_runtime_identity()
        key, digest = decision_cache_key(
            snapshot,
            model=model,
            reasoning_effort=reasoning,
            prompt_version=prompt_version,
        )
        if not hasattr(self, "_ai_decision_cache") or self._ai_decision_cache.path != cache_path:
            self._ai_decision_cache = AIDecisionCache(cache_path)
        decision = self._ai_decision_cache.get(
            key,
            model=model,
            reasoning_effort=reasoning,
            prompt_version=prompt_version,
            expected_snapshot_hash=digest,
        )
        if decision is None:
            if mode == AI_CACHE_ONLY:
                raise RuntimeError(
                    "AI decision cache miss in CACHE_ONLY mode. Generate this causal "
                    "decision with CRYPTO_STRATEGY_AI_MODE=CACHE_THEN_API, then rerun "
                    "the backtest from the cached decisions."
                )
            client = OpenAIDecisionClient(
                model=model,
                reasoning_effort=reasoning,
                prompt_version=prompt_version,
            )
            decision = client.decide(snapshot, snapshot_digest=digest)
            self._ai_decision_cache.put(key, decision)

        self._ai_decisions_by_index[int(i)] = decision
        return decision

    def _build_result_row(self, p, row_kind, positions):
        row = super()._build_result_row(p, row_kind, positions)
        if getattr(self, "signal_strategy_mode", "DI") != OPENAI_DECISION_MODE:
            return row
        index = row.get("research_signal_index")
        try:
            decision = getattr(self, "_ai_decisions_by_index", {}).get(int(index))
        except (TypeError, ValueError):
            decision = None
        if decision is None:
            return row
        row.update(
            ai_long_confidence=decision.long_confidence,
            ai_short_confidence=decision.short_confidence,
            ai_selected_confidence=decision.selected_confidence,
            ai_decision_strength=decision.decision_strength,
            ai_conflict_level=decision.conflict_level,
            ai_key_long_factors=" | ".join(decision.key_long_factors),
            ai_key_short_factors=" | ".join(decision.key_short_factors),
            ai_decision_summary=decision.summary,
            ai_model=decision.model,
            ai_reasoning_effort=decision.reasoning_effort,
            ai_prompt_version=decision.prompt_version,
            ai_snapshot_hash=decision.snapshot_hash,
            ai_response_id=decision.response_id,
            ai_cache_hit=decision.cache_hit,
        )
        return row
