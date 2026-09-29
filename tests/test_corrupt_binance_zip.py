from pathlib import Path

import pytest

from crypto_strategy_lab.data.binance.base_adapter import open_csv_stream


def test_corrupt_binance_zip_reports_exact_archive_path(tmp_path: Path):
    archive = tmp_path / "BTCUSDT-4h-2026-01.zip"
    archive.write_bytes(b"not-a-real-zip")

    with pytest.raises(ValueError, match="Corrupt Binance ZIP archive") as exc:
        with open_csv_stream(archive) as stream:
            stream.read()

    assert str(archive) in str(exc.value)
    assert "Delete/re-download" in str(exc.value)
