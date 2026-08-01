import csv
import zipfile

import pytest

from combine_binance_data import BINANCE_COLUMNS, combine


def _write_zip(path, member, rows, header=True):
    lines = []
    if header:
        lines.append(",".join(BINANCE_COLUMNS))
    lines.extend(",".join(row) for row in rows)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, "\n".join(lines) + "\n")


def _row(timestamp):
    return [str(timestamp), "1", "2", "0.5", "1.5", "10", str(timestamp + 1), "1", "2", "3", "4", "0"]


def test_combines_months_in_order_and_removes_boundary_duplicate(tmp_path):
    folder = tmp_path / "monthly"
    folder.mkdir()
    _write_zip(folder / "BTCUSDT-1h-2025-02.zip", "feb.csv", [_row(2000), _row(3000)])
    _write_zip(folder / "BTCUSDT-1h-2025-01.zip", "jan.csv", [_row(1000), _row(2000)])

    output = tmp_path / "combined.csv"
    rows, duplicates = combine(folder, output)

    with output.open(newline="", encoding="utf-8") as stream:
        result = list(csv.reader(stream))
    assert rows == 3
    assert duplicates == 1
    assert result[0] == BINANCE_COLUMNS
    assert [row[0] for row in result[1:]] == ["1000", "2000", "3000"]


def test_supports_headerless_binance_files(tmp_path):
    folder = tmp_path / "daily"
    folder.mkdir()
    _write_zip(folder / "BTCUSDT-1m-2025-01-01.zip", "day.csv", [_row(1000)], header=False)

    output = tmp_path / "combined.csv"
    combine(folder, output)

    assert output.read_text(encoding="utf-8").splitlines()[0] == ",".join(BINANCE_COLUMNS)


def test_does_not_replace_existing_output_on_invalid_input(tmp_path):
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "bad.csv").write_text("open_time,open\n1\n", encoding="utf-8")
    output = tmp_path / "combined.csv"
    output.write_text("keep me", encoding="utf-8")

    with pytest.raises(ValueError):
        combine(folder, output)
    assert output.read_text(encoding="utf-8") == "keep me"
