"""Output directory management for backtest runs."""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import BacktestConfig


def _safe_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._-")


def _format_number(value: float) -> str:
    return f"{value:g}".replace(".", "p")


def infer_symbol(config: BacktestConfig) -> str:
    stem = Path(config.strategy_csv or config.input_csv).stem.upper()
    match = re.match(r"([A-Z]+?)(?:USDT|USD|BTC|ETH)?(?:_|-|$)", stem)
    return match.group(1) if match else "BACKTEST"


def run_folder_name(config: BacktestConfig, timestamp: datetime | None = None) -> str:
    stamp = (timestamp or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    base = "_".join([
        infer_symbol(config),
        f"{config.strategy_timeframe_minutes}m",
        f"ATR{config.atr_period}",
        f"SL{_format_number(config.sl_mult)}",
        f"TP{_format_number(config.tp_mult)}",
        stamp,
    ])
    run_name = _safe_part(config.run_name or "")
    return f"{run_name}_{base}" if run_name else base


def planned_run_dir(config: BacktestConfig) -> Path:
    if config.output_run_dir is not None:
        return Path(config.output_run_dir)
    return Path(config.output_dir) / run_folder_name(config)


def create_run_dir(config: BacktestConfig) -> Path:
    path = planned_run_dir(config)
    counter = 1
    while path.exists():
        path = path.with_name(f"{path.name}_{counter}")
        counter += 1
    path.mkdir(parents=True, exist_ok=False)
    (path / "charts").mkdir(exist_ok=True)
    return path


def config_to_dict(config: BacktestConfig) -> dict[str, Any]:
    raw = asdict(config) if is_dataclass(config) else {f.name: getattr(config, f.name) for f in fields(BacktestConfig)}
    return {key: _jsonable(value) for key, value in raw.items()}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def write_config(config: BacktestConfig, run_dir: Path) -> None:
    (run_dir / "config.json").write_text(json.dumps(config_to_dict(config), indent=2, default=str))


def write_summary_txt(summary: dict[str, Any], run_dir: Path) -> None:
    lines = [f"{key}: {value}" for key, value in summary.items() if key != "exit_combinations"]
    (run_dir / "summary.txt").write_text("\n".join(lines) + "\n")


def write_run_info(config: BacktestConfig, summary: dict[str, Any], run_dir: Path) -> None:
    lines = [
        "Backtest Run Information",
        "========================",
        f"Output folder: {run_dir.resolve()}",
        f"Run name: {config.run_name or '(none)'}",
        f"Strategy CSV: {config.strategy_csv}",
        f"Intrabar CSV: {config.intrabar_csv if config.use_intrabar_data else '(disabled)'}",
        f"Symbol: {infer_symbol(config)}",
        f"Strategy timeframe: {config.strategy_timeframe_minutes}m",
        f"Risk mode: {config.risk_mode.value}",
        f"ATR period/multiplier: {config.atr_period} / {config.atr_multiplier}",
        f"SL/TP multiples: {config.sl_mult} / {config.tp_mult}",
        f"Initial equity: {config.initial_equity}",
        f"Total pairs: {summary.get('total_pairs')}",
        f"Ending equity: {summary.get('ending_equity')}",
        f"Total return %: {summary.get('total_return_percentage')}",
    ]
    (run_dir / "run_info.txt").write_text("\n".join(lines) + "\n")


def compatible_resample_freq(freq: str) -> str:
    """Map legacy pandas aliases to modern aliases by default."""
    return {"M": "ME", "Y": "YE"}.get(freq, freq)


def periodic_results(trades: pd.DataFrame, freq: str) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["period", "pair_count", "net_pnl", "net_r"])
    exits = pd.to_datetime(trades[["long_exit_time", "short_exit_time"]].max(axis=1))
    frame = trades.assign(exit_time=exits).set_index("exit_time")
    candidates = [compatible_resample_freq(freq)]
    fallback = {"ME": "M", "YE": "Y", "M": "ME", "Y": "YE"}.get(candidates[0])
    if fallback and fallback not in candidates:
        candidates.append(fallback)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return frame.resample(candidate).agg(pair_count=("pair_net_pnl", "size"), net_pnl=("pair_net_pnl", "sum"), net_r=("pair_net_r", "sum")).reset_index(names="period")
        except ValueError as exc:
            last_error = exc
    raise last_error if last_error is not None else ValueError(f"Unsupported resample frequency: {freq}")


def update_latest(output_root: Path, run_dir: Path) -> None:
    latest = output_root / "latest"
    if latest.exists() or latest.is_symlink():
        if latest.is_symlink() or latest.is_file():
            latest.unlink()
        else:
            shutil.rmtree(latest)
    try:
        latest.symlink_to(run_dir.resolve(), target_is_directory=True)
    except OSError:
        shutil.copytree(run_dir, latest)
