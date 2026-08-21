"""Causal intraperiod order-flow research from Binance aggregate trades."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind

from .base import FeatureDefinition


AGG_TRADE_FLOW_FEATURE_NAME = "agg_trade_flow"
AGG_TRADE_FLOW_FEATURE_VERSION = "1"


def _pressure_state(imbalance: np.ndarray, counts: np.ndarray) -> np.ndarray:
    state = np.full(len(imbalance), "NO_TRADES", dtype=object)
    active = counts > 0
    state[active] = "BALANCED"
    state[active & np.isfinite(imbalance) & (imbalance > 0.05)] = "BUY_PRESSURE"
    state[active & np.isfinite(imbalance) & (imbalance < -0.05)] = "SELL_PRESSURE"
    return state


@dataclass(frozen=True, slots=True)
class AggTradeFlowFeatureProvider:
    """Aggregate only aggTrades occurring inside each completed strategy candle."""

    definition: FeatureDefinition = FeatureDefinition(
        name=AGG_TRADE_FLOW_FEATURE_NAME,
        version=AGG_TRADE_FLOW_FEATURE_VERSION,
        required_datasets=(DatasetKind.KLINES, DatasetKind.AGG_TRADES),
        output_columns=(
            "agg_source_last_event_at",
            "agg_last_event_age_seconds",
            "agg_trade_count",
            "agg_underlying_trade_count",
            "agg_base_volume",
            "agg_quote_volume",
            "agg_taker_buy_base_volume",
            "agg_taker_sell_base_volume",
            "agg_taker_buy_quote_volume",
            "agg_taker_sell_quote_volume",
            "agg_taker_buy_sell_ratio",
            "agg_taker_buy_share",
            "agg_taker_imbalance",
            "agg_aggressor_state",
            "agg_trade_vwap",
            "agg_trade_vwap_to_close_bps",
        ),
        warmup_bars=0,
        availability_rule="agg_trades_with_event_time_inside_completed_strategy_candle",
    )

    def compute(
        self,
        request: DataRequest,
        datasets: Mapping[DatasetKind, pd.DataFrame],
        parameters: Mapping[str, object],
        feature_frames: Mapping[str, pd.DataFrame] | None = None,
    ) -> pd.DataFrame:
        del parameters, feature_frames
        try:
            klines = datasets[DatasetKind.KLINES].copy()
            trades = datasets[DatasetKind.AGG_TRADES].copy()
        except KeyError as exc:
            raise ValueError("agg_trade_flow requires klines and agg_trades") from exc

        required_kline = {"period_start", "period_end", "available_at", "close"}
        missing_kline = sorted(required_kline - set(klines.columns))
        if missing_kline:
            raise ValueError(f"Canonical kline frame is missing columns: {missing_kline}")
        required_trade = {"event_time", "available_at", "price", "quantity", "is_buyer_maker"}
        missing_trade = sorted(required_trade - set(trades.columns))
        if missing_trade:
            raise ValueError(f"Canonical aggTrades frame is missing columns: {missing_trade}")
        if klines.empty:
            raise ValueError("Cannot align aggregate trade flow to an empty kline frame")

        klines = klines.sort_values("period_start", kind="stable").drop_duplicates(
            "period_start", keep="last"
        ).reset_index(drop=True)
        starts = pd.DatetimeIndex(pd.to_datetime(klines["period_start"], utc=True))
        ends = pd.DatetimeIndex(pd.to_datetime(klines["period_end"], utc=True))
        decision = pd.DatetimeIndex(pd.to_datetime(klines["available_at"], utc=True))
        close = pd.to_numeric(klines["close"], errors="raise").to_numpy(float)
        n = len(klines)

        count = np.zeros(n, dtype=np.int64)
        underlying_count = np.zeros(n, dtype=np.int64)
        base_volume = np.zeros(n, dtype=float)
        quote_volume = np.zeros(n, dtype=float)
        buy_base = np.zeros(n, dtype=float)
        sell_base = np.zeros(n, dtype=float)
        buy_quote = np.zeros(n, dtype=float)
        sell_quote = np.zeros(n, dtype=float)
        weighted_price = np.zeros(n, dtype=float)
        last_event_ns = np.full(n, np.iinfo(np.int64).min, dtype=np.int64)

        if not trades.empty:
            event = pd.DatetimeIndex(pd.to_datetime(trades["event_time"], utc=True))
            available = pd.DatetimeIndex(pd.to_datetime(trades["available_at"], utc=True))
            price = pd.to_numeric(trades["price"], errors="raise").to_numpy(float)
            quantity = pd.to_numeric(trades["quantity"], errors="raise").to_numpy(float)
            quote = (
                pd.to_numeric(trades["quote_quantity"], errors="coerce").to_numpy(float)
                if "quote_quantity" in trades.columns
                else price * quantity
            )
            buyer_maker = trades["is_buyer_maker"].astype(bool).to_numpy(bool)
            if {"first_trade_id", "last_trade_id"}.issubset(trades.columns):
                first_id = pd.to_numeric(trades["first_trade_id"], errors="raise").to_numpy(np.int64)
                last_id = pd.to_numeric(trades["last_trade_id"], errors="raise").to_numpy(np.int64)
                underlying = last_id - first_id + 1
            else:
                underlying = np.ones(len(trades), dtype=np.int64)

            indices = np.searchsorted(ends.asi8, event.asi8, side="right")
            in_range = indices < n
            safe_indices = np.minimum(indices, n - 1)
            valid = in_range.copy()
            valid &= event.asi8 >= starts.asi8[safe_indices]
            valid &= event.asi8 < ends.asi8[safe_indices]
            valid &= available.asi8 <= decision.asi8[safe_indices]

            idx = indices[valid].astype(np.int64)
            event_ns = event.asi8[valid]
            p = price[valid]
            q = quantity[valid]
            qq = quote[valid]
            maker = buyer_maker[valid]
            underlying = underlying[valid]

            np.add.at(count, idx, 1)
            np.add.at(underlying_count, idx, underlying)
            np.add.at(base_volume, idx, q)
            np.add.at(quote_volume, idx, qq)
            np.add.at(weighted_price, idx, p * q)
            np.add.at(buy_base, idx[~maker], q[~maker])
            np.add.at(sell_base, idx[maker], q[maker])
            np.add.at(buy_quote, idx[~maker], qq[~maker])
            np.add.at(sell_quote, idx[maker], qq[maker])
            np.maximum.at(last_event_ns, idx, event_ns)

        buy_sell_ratio = np.divide(
            buy_base,
            sell_base,
            out=np.full(n, np.nan, dtype=float),
            where=sell_base > 0,
        )
        buy_share = np.divide(
            buy_base,
            base_volume,
            out=np.full(n, np.nan, dtype=float),
            where=base_volume > 0,
        )
        imbalance = np.divide(
            buy_base - sell_base,
            base_volume,
            out=np.full(n, np.nan, dtype=float),
            where=base_volume > 0,
        )
        vwap = np.divide(
            weighted_price,
            base_volume,
            out=np.full(n, np.nan, dtype=float),
            where=base_volume > 0,
        )
        vwap_to_close = np.divide(
            vwap - close,
            close,
            out=np.full(n, np.nan, dtype=float),
            where=np.isfinite(vwap) & np.isfinite(close) & (close != 0),
        ) * 10000.0

        has_event = count > 0
        last_event = pd.Series(pd.NaT, index=range(n), dtype="datetime64[ns, UTC]")
        if bool(has_event.any()):
            last_event.loc[has_event] = pd.to_datetime(last_event_ns[has_event], utc=True)
        available_series = pd.Series(decision)
        output = pd.DataFrame(
            {
                "timestamp": starts,
                "available_at": decision,
                "agg_source_last_event_at": last_event,
                "agg_trade_count": count,
                "agg_underlying_trade_count": underlying_count,
                "agg_base_volume": base_volume,
                "agg_quote_volume": quote_volume,
                "agg_taker_buy_base_volume": buy_base,
                "agg_taker_sell_base_volume": sell_base,
                "agg_taker_buy_quote_volume": buy_quote,
                "agg_taker_sell_quote_volume": sell_quote,
                "agg_taker_buy_sell_ratio": buy_sell_ratio,
                "agg_taker_buy_share": buy_share,
                "agg_taker_imbalance": imbalance,
                "agg_aggressor_state": _pressure_state(imbalance, count),
                "agg_trade_vwap": vwap,
                "agg_trade_vwap_to_close_bps": vwap_to_close,
            }
        )
        output["agg_last_event_age_seconds"] = (
            available_series - output["agg_source_last_event_at"]
        ).dt.total_seconds()

        leak = output["agg_source_last_event_at"].notna() & (
            output["agg_source_last_event_at"] > output["available_at"]
        )
        if bool(leak.any()):
            raise AssertionError("Aggregate trade flow attached a future trade event")

        output.attrs.update(
            {
                "feature_name": self.definition.name,
                "feature_version": self.definition.version,
                "effective_warmup_bars": self.definition.warmup_bars,
                "request_cache_key": request.cache_key(),
            }
        )
        return output
