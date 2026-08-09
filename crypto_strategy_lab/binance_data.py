"""Download and incrementally update public Binance Spot OHLCV data."""
from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

BASE_URL = "https://data-api.binance.vision/api/v3/klines"
INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}
COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


def _utc_ms(value: str | None, *, end_of_day: bool = False) -> int | None:
    if not value:
        return None
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    if end_of_day and len(value.strip()) <= 10:
        stamp += pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
    return int(stamp.timestamp() * 1000)


def _last_timestamp(path: Path) -> int | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    frame = pd.read_csv(path, usecols=["timestamp"])
    if frame.empty:
        return None
    raw = frame["timestamp"].iloc[-1]
    if isinstance(raw, str) and not raw.strip().isdigit():
        return int(pd.Timestamp(raw).timestamp() * 1000)
    return int(raw)


def _request(params: dict, opener=urlopen, retries: int = 5) -> list:
    url = f"{BASE_URL}?{urlencode(params)}"
    for attempt in range(retries):
        try:
            with opener(Request(url, headers={"User-Agent": "Crypto-Strategy-Lab/1.0"}), timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict):
                raise RuntimeError(payload.get("msg", str(payload)))
            return payload
        except HTTPError as exc:
            if exc.code not in (418, 429, 500, 502, 503, 504) or attempt == retries - 1:
                detail = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Binance returned HTTP {exc.code}: {detail}") from exc
            time.sleep(float(exc.headers.get("Retry-After", min(2 ** attempt, 10))))
        except URLError as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"Could not reach Binance: {exc.reason}") from exc
            time.sleep(min(2 ** attempt, 10))
    return []


def download_klines(
    symbol: str,
    interval: str,
    destination: str | Path,
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    progress=None,
    cancelled=None,
    opener=urlopen,
) -> dict:
    """Download closed Spot candles with a persistent, resumable checkpoint."""
    symbol = symbol.strip().upper().replace("/", "")
    if not symbol or not symbol.isalnum():
        raise ValueError("Enter a valid Binance symbol such as BTCUSDT.")
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported timeframe: {interval}")
    step = INTERVAL_MS[interval]
    destination = Path(destination).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    last = _last_timestamp(destination)
    checkpoint = destination.with_name(f".{destination.name}.download")
    checkpoint_last = _last_timestamp(checkpoint)
    saved_last = max(value for value in (last, checkpoint_last) if value is not None) if last is not None or checkpoint_last is not None else None
    start_ms = saved_last + step if saved_last is not None else (_utc_ms(start_date) or 0)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    last_closed_ms = (now_ms // step) * step - 1
    end_ms = min(_utc_ms(end_date, end_of_day=True) or last_closed_ms, last_closed_ms)
    if start_ms > end_ms and not checkpoint.exists():
        return {"path": str(destination), "added": 0, "total": sum(1 for _ in destination.open(encoding="utf-8")) - 1 if destination.exists() else 0}

    added = max(0, sum(1 for _ in checkpoint.open(encoding="utf-8")) - 1) if checkpoint.exists() else 0
    try:
        mode = "a" if checkpoint.exists() and checkpoint.stat().st_size else "w"
        with checkpoint.open(mode, encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            if mode == "w":
                writer.writerow(COLUMNS)
            cursor = start_ms
            while cursor <= end_ms:
                if cancelled and cancelled():
                    raise InterruptedError("Download cancelled")
                rows = _request({"symbol": symbol, "interval": interval, "startTime": cursor, "endTime": end_ms, "limit": 1000}, opener=opener)
                if not rows:
                    break
                for row in rows:
                    open_time = int(row[0])
                    if open_time > end_ms:
                        break
                    writer.writerow((open_time, row[1], row[2], row[3], row[4], row[5])); added += 1
                next_cursor = int(rows[-1][0]) + step
                if next_cursor <= cursor:
                    raise RuntimeError("Binance returned a non-advancing candle page.")
                cursor = next_cursor
                stream.flush()
                os.fsync(stream.fileno())
                if progress:
                    progress(added, pd.to_datetime(rows[-1][0], unit="ms", utc=True).strftime("%Y-%m-%d %H:%M UTC"))
                if len(rows) < 1000:
                    break

        # Merge the completed checkpoint once, then atomically publish it. The
        # destination remains usable by backtests throughout the download.
        fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        os.close(fd); temporary = Path(temporary_name)
        try:
            if destination.exists() and destination.stat().st_size:
                shutil.copyfile(destination, temporary)
                merge_mode = "a"
            else:
                merge_mode = "w"
            with temporary.open(merge_mode, encoding="utf-8", newline="") as output, checkpoint.open("r", encoding="utf-8", newline="") as source:
                writer = csv.writer(output, lineterminator="\n")
                if merge_mode == "w":
                    writer.writerow(COLUMNS)
                reader = csv.reader(source); next(reader, None)
                for row in reader:
                    if row and (last is None or int(row[0]) > last):
                        writer.writerow(row)
                output.flush(); os.fsync(output.fileno())
            os.replace(temporary, destination)
            checkpoint.unlink(missing_ok=True)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    except Exception:
        # Keep the checkpoint on cancellation, application shutdown, or a
        # network failure. The next run resumes after its last saved candle.
        raise
    total = sum(1 for _ in destination.open(encoding="utf-8")) - 1
    return {"path": str(destination), "added": added, "total": max(0, total)}
