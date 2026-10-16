"""Operator-local V2 historical chart parity capture.

Compares the canonical desktop CompletedRunVisualizer model with the active
browser V2 HTTP payload for one verified completed run. Evidence is written
only to the operator-selected local directory; no run, cache, or config is
modified.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import urlopen

from crypto_strategy_lab.browser_chart_parity import canonical_sha256, compare_payloads
from crypto_strategy_lab.browser_readonly_service import build_browser_readonly_service
from crypto_strategy_lab.browser_visualizer_adapter import load_browser_visualizer
from crypto_strategy_lab.paths import OUTPUT_DIR
from crypto_strategy_lab.strategy_visualizer import CompletedRunVisualizer
from crypto_strategy_lab.strategy_visualizer_browser_v2 import StrategyVisualizerV2BrowserServer


DEFAULT_RUN_ID = "BTCUSDT_4h_ad58a712d8e7492380b99ec96c20c80f"
DEFAULT_TIMEFRAMES = ("1h", "4h", "1d")
FROZEN_TRADE_COUNT = 79


def _available_timeframes(model: Any) -> list[str]:
    values: list[str] = []
    for item in model.available_chart_timeframes():
        interval = str(item.get("interval") or "").strip().lower()
        if interval and interval not in values:
            values.append(interval)
    strategy = str(model.seed.request.strategy_timeframe or "").strip().lower()
    if strategy and strategy not in values:
        values.append(strategy)
    return values


def representative_trade_indices(model: Any) -> list[int]:
    count = int(model.trade_count)
    if count <= 0:
        raise ValueError("Completed run contains no trades")
    indices = {0, count // 2, count - 1}
    trades = getattr(model, "trades", None)
    if trades is not None:
        try:
            for side in ("LONG", "SHORT"):
                for index, (_, row) in enumerate(trades.iterrows()):
                    if str(row.get("side") or "").upper() == side:
                        indices.add(index)
                        break
        except (AttributeError, TypeError):
            pass
    return sorted(index for index in indices if 0 <= index < count)


def parity_cases(model: Any, requested_timeframes: tuple[str, ...] = DEFAULT_TIMEFRAMES) -> list[tuple[int, str]]:
    available = _available_timeframes(model)
    chosen = [tf for tf in requested_timeframes if tf in available]
    strategy = str(model.seed.request.strategy_timeframe or "").strip().lower()
    if strategy and strategy in available and strategy not in chosen:
        chosen.append(strategy)
    if not chosen:
        chosen = available[:1]
    if not chosen:
        raise ValueError("No chart timeframe is available for the completed run")
    return [(index, timeframe) for index in representative_trade_indices(model) for timeframe in chosen]


def _http_payload(base_url: str, trade_index: int, chart_timeframe: str) -> Any:
    query = urlencode({"trade_index": trade_index, "chart_timeframe": chart_timeframe})
    with urlopen(base_url + "api/payload?" + query, timeout=30) as response:
        return json.loads(
            response.read().decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )


def capture_parity(
    desktop_model: Any,
    browser_model: Any,
    evidence_dir: Path,
    *,
    requested_timeframes: tuple[str, ...] = DEFAULT_TIMEFRAMES,
    browser_payload: Callable[[int, str], Any] | None = None,
) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    # A failed capture must never leave an earlier PASS summary as current evidence.
    (evidence_dir / "summary.json").unlink(missing_ok=True)
    if int(desktop_model.trade_count) != int(browser_model.trade_count):
        raise ValueError("Desktop and browser trade counts differ")
    if str(desktop_model.manifest.get("run_id") or desktop_model.run_dir.name) != str(browser_model.manifest.get("run_id") or browser_model.run_dir.name):
        raise ValueError("Desktop and browser run identities differ")
    cases = parity_cases(desktop_model, requested_timeframes)
    # A frozen baseline capture is not certified with a silently reduced
    # timeframe matrix; reject missing columns before any browser server starts.
    run_id = str(desktop_model.manifest.get("run_id") or desktop_model.run_dir.name)
    if run_id == DEFAULT_RUN_ID:
        required = {(index, tf) for index in (0, FROZEN_TRADE_COUNT // 2, FROZEN_TRADE_COUNT - 1)
                    for tf in DEFAULT_TIMEFRAMES}
        if not required.issubset(set(cases)):
            raise ValueError("Frozen V2 chart parity requires first/middle/last trades on 1h, 4h and 1d")
    results: list[dict[str, Any]] = []

    server = None
    if browser_payload is None:
        server = StrategyVisualizerV2BrowserServer(browser_model)
        base_url = server.start()
        browser_payload = lambda index, timeframe: _http_payload(base_url, index, timeframe)

    try:
        for trade_index, timeframe in cases:
            desktop = desktop_model.build_v2_diagnostic_payload(
                trade_index=trade_index,
                chart_timeframe=timeframe,
            )
            browser = browser_payload(trade_index, timeframe)
            differences = compare_payloads(desktop, browser)
            stem = f"trade_{trade_index:03d}_{timeframe}"
            desktop_path = evidence_dir / f"desktop_{stem}.json"
            browser_path = evidence_dir / f"browser_{stem}.json"
            desktop_path.write_text(
                json.dumps(desktop, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False),
                encoding="utf-8",
            )
            browser_path.write_text(
                json.dumps(browser, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False),
                encoding="utf-8",
            )
            results.append(
                {
                    "trade_index": trade_index,
                    "timeframe": timeframe,
                    "desktop_sha256": canonical_sha256(desktop),
                    "browser_sha256": canonical_sha256(browser),
                    "exact_match": not differences,
                    "mismatches": differences[:20],
                }
            )
    finally:
        if server is not None:
            server.stop()

    summary = {
        "run_id": str(desktop_model.manifest.get("run_id") or desktop_model.run_dir.name),
        "trade_count": int(desktop_model.trade_count),
        "available_timeframes": _available_timeframes(desktop_model),
        "cases": results,
        "pass": all(item["exact_match"] for item in results),
    }
    (evidence_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return summary



def review_captured_parity(evidence_dir: Path) -> dict[str, Any]:
    """Independently review the frozen local V2 capture, without loading market data.

    Fail closed on missing, altered, inconsistent or incomplete files. The
    capture remains local; this command prints no candle/trade payload content.
    """
    evidence_dir = Path(evidence_dir)
    def read_json(path: Path) -> Any:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )

    summary = read_json(evidence_dir / "summary.json")
    if not isinstance(summary, dict):
        raise ValueError("Invalid V2 parity summary")
    if summary.get("run_id") != DEFAULT_RUN_ID or type(summary.get("trade_count")) is not int or summary["trade_count"] != FROZEN_TRADE_COUNT:
        raise ValueError("Frozen run identity or trade count mismatch")
    cases = summary.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Missing parity cases")

    seen: set[tuple[int, str]] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Malformed parity case")
        index, timeframe = case.get("trade_index"), case.get("timeframe")
        if type(index) is not int or not 0 <= index < FROZEN_TRADE_COUNT or not isinstance(timeframe, str) or not timeframe.isalnum():
            raise ValueError("Invalid parity case identity")
        key = (index, timeframe)
        if key in seen:
            raise ValueError("Duplicate parity case")
        seen.add(key)
        stem = f"trade_{index:03d}_{timeframe}"
        desktop = read_json(evidence_dir / f"desktop_{stem}.json")
        browser = read_json(evidence_dir / f"browser_{stem}.json")
        for label, payload in (("desktop", desktop), ("browser", browser)):
            if (not isinstance(payload, dict)
                    or not isinstance(payload.get("run"), dict)
                    or payload["run"].get("runId") != DEFAULT_RUN_ID
                    or payload.get("selectedTradeIndex") != index
                    or payload.get("chartTimeframe") != timeframe
                    or payload["run"].get("chartTimeframe") != timeframe):
                raise ValueError(
                    f"Captured {label} payload identity mismatch: trade={index}, timeframe={timeframe}"
                )
        desktop_hash = canonical_sha256(desktop)
        browser_hash = canonical_sha256(browser)
        if (desktop_hash != case.get("desktop_sha256")
                or browser_hash != case.get("browser_sha256")
                or desktop_hash != browser_hash
                or compare_payloads(desktop, browser)
                or case.get("exact_match") is not True
                or case.get("mismatches") != []):
            raise ValueError(f"Captured payload differs: trade={index}, timeframe={timeframe}")

    required = {(index, timeframe) for index in (0, 39, 78) for timeframe in DEFAULT_TIMEFRAMES}
    if not required.issubset(seen):
        raise ValueError("Frozen first/middle/last trade and timeframe matrix incomplete")
    if summary.get("pass") is not True:
        raise ValueError("Parity summary is not PASS")
    return {"run_id": DEFAULT_RUN_ID, "trade_count": FROZEN_TRADE_COUNT, "cases_checked": len(seen), "pass": True}


def _output_root(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    env = os.environ.get("CRYPTO_STRATEGY_LAB_OUTPUT_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (OUTPUT_DIR / "data_lake_v2").resolve()


def load_models(run_id: str, output_root: Path):
    service = build_browser_readonly_service()
    application = service.application_service
    if application is None:
        raise RuntimeError("Browser application service is unavailable")
    run_dir = output_root / run_id
    manifest, _summary = application.completed_runs.read(run_dir)
    desktop_model = CompletedRunVisualizer.load(application, run_dir, manifest)
    browser_model = load_browser_visualizer(application, output_root, run_id)
    return desktop_model, browser_model


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--output-root")
    parser.add_argument("--review-only", action="store_true", help="Verify retained local V2 parity captures without the Data Lake")
    parser.add_argument(
        "--evidence-dir",
        default="parity_verification/v2_historical_chart",
        help="Local-only evidence directory; do not commit captured payloads.",
    )
    args = parser.parse_args(argv)

    if args.review_only:
        review = review_captured_parity(Path(args.evidence_dir))
        print(f"V2 historical capture review: PASS ({review['cases_checked']} cases; {review['trade_count']} trades)")
        return 0

    # Fail closed even when canonical model loading fails before capture_parity starts.
    evidence_dir = Path(args.evidence_dir)
    (evidence_dir / "summary.json").unlink(missing_ok=True)
    output_root = _output_root(args.output_root)
    desktop_model, browser_model = load_models(args.run_id, output_root)
    if args.run_id == DEFAULT_RUN_ID:
        if int(desktop_model.trade_count) != FROZEN_TRADE_COUNT or int(browser_model.trade_count) != FROZEN_TRADE_COUNT:
            raise ValueError("Frozen BTCUSDT baseline must contain exactly 79 trades")
        for model in (desktop_model, browser_model):
            if str(model.manifest.get("run_id") or model.run_dir.name) != DEFAULT_RUN_ID:
                raise ValueError("Frozen BTCUSDT run identity mismatch")
    summary = capture_parity(desktop_model, browser_model, evidence_dir)

    print(f"Run: {summary['run_id']}")
    print(f"Trades: {summary['trade_count']}")
    print(f"Cases: {len(summary['cases'])}")
    for item in summary["cases"]:
        status = "PASS" if item["exact_match"] else "FAIL"
        print(
            f"{status} trade={item['trade_index']} tf={item['timeframe']} "
            f"desktop={item['desktop_sha256']} browser={item['browser_sha256']}"
        )
        for mismatch in item["mismatches"]:
            print("  " + mismatch)
    print("Historical V2 chart payload parity: " + ("PASS" if summary["pass"] else "FAIL"))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
