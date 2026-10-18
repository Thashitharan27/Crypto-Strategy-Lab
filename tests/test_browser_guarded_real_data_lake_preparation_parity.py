"""B2 isolated *real ZIP Data Lake* read/preparation parity across native and HTTP.

Both independently invoked services call the production loader and causal
prepared-frame adapter; no market data, saved runs, or production roots touched.
"""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import zipfile

import pandas as pd
from pandas.testing import assert_frame_equal
from fastapi.testclient import TestClient

from crypto_strategy_lab.browser_guarded_integration import BrowserGuardedIntegration
from crypto_strategy_lab.browser_guarded_output import bind_guarded_output_root
from crypto_strategy_lab.browser_http import create_browser_app
from crypto_strategy_lab.data.backtest_service import load_backtest_bundle
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.gui.v2_controller import GuiApplicationService, GuiResearchRequest
from crypto_strategy_lab.prepared_backtest import from_data_lake_bundle
from crypto_strategy_lab.feature_research import feature_context_frame


def _write_frozen_real_klines(root: Path):
    for date in pd.date_range("2025-12-20", "2026-01-03", freq="D", tz="UTC"):
        directory = root / "raw" / "futures" / "um" / "daily" / "klines" / "BTCUSDT" / "4h"
        directory.mkdir(parents=True, exist_ok=True)
        rows = []
        for n in range(6):
            t = date + pd.Timedelta(hours=n * 4)
            start_ms = int(t.timestamp() * 1000)
            close = 100.0 + (date.day % 9) + n * 0.25
            rows.append(
                f"{start_ms},{close},{close + 1},{close - 1},{close},10,"
                f"{start_ms + 14_399_999},0,1,0,0,0"
            )
        day = date.strftime("%Y-%m-%d")
        destination = directory / f"BTCUSDT-4h-{day}.zip"
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"BTCUSDT-4h-{day}.csv", "\n".join(rows) + "\n")


    # The guarded HTTP request requires an explicit intrabar interval.
    # Supply genuine, contiguous 1m source ZIPs rather than weakening that rule.
    for date in pd.date_range("2026-01-01", "2026-01-02", freq="D", tz="UTC"):
        directory = root / "raw" / "futures" / "um" / "daily" / "klines" / "BTCUSDT" / "1m"
        directory.mkdir(parents=True, exist_ok=True)
        rows = []
        for n in range(1440):
            t = date + pd.Timedelta(minutes=n)
            start_ms = int(t.timestamp() * 1000)
            close = 100.0 + (n % 60) * 0.01
            rows.append(
                f"{start_ms},{close},{close + 0.1},{close - 0.1},{close},10,"
                f"{start_ms + 59_999},0,1,0,0,0"
            )
        day = date.strftime("%Y-%m-%d")
        destination = directory / f"BTCUSDT-1m-{day}.zip"
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"BTCUSDT-1m-{day}.csv", "\n".join(rows) + "\n")


def test_real_zip_loader_and_prepared_frames_match_native_and_guarded_http(tmp_path):
    raw = tmp_path / "lake"
    _write_frozen_real_klines(raw)
    approved = tmp_path / "approved"
    approved.mkdir()
    config = replace(ResearchRunConfig(), data=replace(
        ResearchRunConfig().data, strategy_timeframe_minutes=240,
        intrabar_timeframe_minutes=1, use_intrabar_data=True,
    ))
    captures = []

    class NativePreparedReader:
        def __init__(self, store):
            self.store = store
        def run(self, request, effective, *, refresh_catalog=True):
            bundle = load_backtest_bundle(
                self.store, request,
                refresh_catalog=refresh_catalog,
                research_start=request.start,
                intrabar_start=request.start,
                feature_config=effective.features,
                data_config=effective.data,
            )
            prepared, _ = from_data_lake_bundle(bundle)
            assert bundle.strategy.attrs["canonical_source_identity"]
            assert bundle.intrabar is not None
            assert len(bundle.intrabar) >= 2880
            assert effective.reporting.output_dir == str(approved)
            captures.append((
                request,
                effective.to_dict(),
                bundle.strategy.copy(deep=True),
                feature_context_frame(prepared),
                bundle.strategy.attrs["canonical_source_identity"],
                bundle.intrabar.copy(deep=True),
            ))
            return len(prepared)

    def service(cache):
        native = GuiApplicationService(
            raw, tmp_path / cache,
            runner_factory=lambda _: NativePreparedReader(native.store),
        )
        return native

    request = GuiResearchRequest(
        exchange="binance", market="futures_um", symbol="BTCUSDT",
        period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 1, 3, tzinfo=timezone.utc),
        strategy_timeframe="4h", intrabar_timeframe="1m",
    )
    direct = service("cache-desktop").run(
        request, bind_guarded_output_root(config, approved),
    )

    integration = BrowserGuardedIntegration(
        service("cache-browser"), tmp_path, enabled=True, execution_root=approved,
    )
    token = "z" * 48
    app = create_browser_app(
        token=token, guarded_integration=integration, guarded_enabled=True,
    )
    try:
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post(
                "/api/v1/guarded/jobs",
                headers={"Authorization": "Bearer " + token},
                json={
                    "request_id": "real-zip-prepared-parity",
                    "request": {
                        "exchange": "binance", "market": "futures_um",
                        "symbol": "BTCUSDT",
                        "period_start": "2026-01-01T00:00:00Z",
                        "period_end": "2026-01-03T00:00:00Z",
                        "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
                    },
                    "config": config.to_dict(),
                },
            )
            assert response.status_code == 202, response.text
            browser = integration._jobs.result("real-zip-prepared-parity").result(timeout=60)
            assert client.get(
                "/api/v1/guarded/jobs/real-zip-prepared-parity",
                headers={"Authorization": "Bearer " + token},
            ).json()["status"] == "COMPLETED"
    finally:
        integration.close()

    assert direct == browser
    assert direct >= 12
    assert len(captures) == 2
    assert captures[0][0] == captures[1][0]
    assert captures[0][1] == captures[1][1]
    assert captures[0][4] == captures[1][4]
    assert_frame_equal(captures[0][2], captures[1][2], check_exact=True)
    assert_frame_equal(captures[0][3], captures[1][3], check_exact=True)
    assert_frame_equal(captures[0][5], captures[1][5], check_exact=True)
    assert captures[0][2]["close"].notna().all()


def test_full_native_zip_run_and_manifest_parity_direct_vs_guarded_http(tmp_path):
    """Use the *default* production ResearchRunner/native simulator/reporter.

    Both paths independently load the same immutable ZIP sources. This does
    not replace original Windows market-data certification.
    """
    from crypto_strategy_lab.browser_guarded_recovery_verify import verify_recovered_run
    from crypto_strategy_lab.gui.v2_controller import CompletedRunReader
    from crypto_strategy_lab.run_manifest import artifact_path

    raw = tmp_path / "lake"
    _write_frozen_real_klines(raw)
    output = tmp_path / "approved"
    output.mkdir()
    config = replace(ResearchRunConfig(), data=replace(
        ResearchRunConfig().data,
        strategy_timeframe_minutes=240,
        intrabar_timeframe_minutes=1,
        use_intrabar_data=True,
    ))
    request = GuiResearchRequest(
        exchange="binance", market="futures_um", symbol="BTCUSDT",
        period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 1, 3, tzinfo=timezone.utc),
        strategy_timeframe="4h", intrabar_timeframe="1m",
    )

    # No runner_factory: the actual GUI service composes the existing
    # ResearchRunner + NativeSimulator + canonical manifest reporter.
    direct_service = GuiApplicationService(raw, tmp_path / "native-cache")
    direct = direct_service.run(request, bind_guarded_output_root(config, output))

    browser_service = GuiApplicationService(raw, tmp_path / "browser-cache")
    integration = BrowserGuardedIntegration(
        browser_service, tmp_path, enabled=True, execution_root=output,
    )
    token = "n" * 48
    app = create_browser_app(
        token=token, guarded_integration=integration, guarded_enabled=True,
    )
    try:
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post(
                "/api/v1/guarded/jobs",
                headers={"Authorization": "Bearer " + token},
                json={
                    "request_id": "native-zip-complete",
                    "request": {
                        "exchange": "binance", "market": "futures_um",
                        "symbol": "BTCUSDT",
                        "period_start": "2026-01-01T00:00:00Z",
                        "period_end": "2026-01-03T00:00:00Z",
                        "strategy_timeframe": "4h", "intrabar_timeframe": "1m",
                    },
                    "config": config.to_dict(),
                },
            )
            assert response.status_code == 202, response.text
            browser = integration._jobs.result("native-zip-complete").result(timeout=120)
            status = client.get(
                "/api/v1/guarded/jobs/native-zip-complete",
                headers={"Authorization": "Bearer " + token},
            )
            assert status.status_code == 200
            assert status.json()["status"] == "COMPLETED"
    finally:
        integration.close()

    assert_frame_equal(direct.trades, browser.trades, check_exact=True)
    assert direct.prepared_cache_key == browser.prepared_cache_key
    assert direct.strategy_rows == browser.strategy_rows
    assert direct.prepared_rows == browser.prepared_rows
    assert direct.output_dir != browser.output_dir

    reader = CompletedRunReader()
    native_manifest, native_summary = reader.read(direct.output_dir)
    http_manifest, http_summary = reader.read(browser.output_dir)
    assert native_summary == http_summary
    for section in ("request", "config", "hashes", "catalog", "prepared"):
        assert native_manifest[section] == http_manifest[section]
    assert (
        native_manifest["research"]["trade_fingerprint"]
        == http_manifest["research"]["trade_fingerprint"]
    )
    assert set(native_manifest["artifacts"]) == set(http_manifest["artifacts"])
    for run, manifest in (
        (direct.output_dir, native_manifest),
        (browser.output_dir, http_manifest),
    ):
        for name in manifest["artifacts"]:
            artifact_path(run, manifest, name, verify=True)
        assert verify_recovered_run(output, Path(run).name)["status"] == "ARTIFACTS_VERIFIED"
    for name in ("trades", "trade_csv", "signals", "summary"):
        assert artifact_path(direct.output_dir, native_manifest, name).read_bytes() == (
            artifact_path(browser.output_dir, http_manifest, name).read_bytes()
        )
