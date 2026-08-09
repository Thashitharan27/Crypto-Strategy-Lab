"""Combine Binance kline CSV/ZIP files into one chronological CSV file."""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from itertools import chain
from pathlib import Path
from typing import Iterator, TextIO


BINANCE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]
DATE_PATTERN = re.compile(r"-(\d{4})-(\d{2})(?:-(\d{2}))?(?:\.csv|\.zip)$", re.IGNORECASE)


def _sort_key(path: Path) -> tuple[int, int, int, str]:
    match = DATE_PATTERN.search(path.name)
    if match:
        year, month, day = match.groups()
        return int(year), int(month), int(day or 0), path.name.lower()
    return 9999, 99, 99, path.name.lower()


def find_inputs(folder: Path, output: Path) -> list[Path]:
    """Return supported source files in Binance filename/date order."""
    output = output.resolve()
    inputs = [
        path for path in folder.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".zip", ".csv"}
        and path.resolve() != output
    ]
    return sorted(inputs, key=_sort_key)


@contextmanager
def _csv_streams(path: Path) -> Iterator[Iterator[tuple[str, TextIO]]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            yield iter([(path.name, stream)])
        return

    with zipfile.ZipFile(path) as archive:
        members = sorted(
            (item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".csv")),
            key=lambda item: item.filename.lower(),
        )
        if not members:
            raise ValueError(f"{path.name} contains no CSV file")

        def streams() -> Iterator[tuple[str, TextIO]]:
            for member in members:
                with archive.open(member) as binary:
                    with TextIOWrapper(binary, encoding="utf-8-sig", newline="") as text:
                        yield f"{path.name}:{member.filename}", text

        from io import TextIOWrapper
        yield streams()


def combine(folder: Path, output: Path) -> tuple[int, int]:
    """Combine files and return (rows_written, duplicate_rows_skipped)."""
    folder = folder.resolve()
    output = output.resolve()
    if not folder.is_dir():
        raise ValueError(f"Input folder does not exist: {folder}")

    inputs = find_inputs(folder, output)
    if not inputs:
        raise ValueError(f"No .zip or .csv files found in {folder}")

    output.parent.mkdir(parents=True, exist_ok=True)
    rows_written = duplicates = 0
    seen_times: set[str] = set()
    expected_header: list[str] | None = None

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, text=True
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with temporary.open("w", encoding="utf-8", newline="") as destination:
            writer = csv.writer(destination, lineterminator="\n")
            for source in inputs:
                with _csv_streams(source) as streams:
                    for label, stream in streams:
                        reader = csv.reader(stream)
                        first = next(reader, None)
                        if first is None:
                            continue
                        has_header = bool(first and first[0].strip().lower() in {"open_time", "timestamp"})
                        header = [cell.strip() for cell in first] if has_header else BINANCE_COLUMNS[:len(first)]
                        if expected_header is None:
                            expected_header = header
                            writer.writerow(header)
                        elif header != expected_header:
                            raise ValueError(f"Column mismatch in {label}")

                        rows = reader if has_header else chain((first,), reader)
                        for line_number, row in enumerate(rows, start=2 if has_header else 1):
                            if not row or not any(cell.strip() for cell in row):
                                continue
                            if len(row) != len(expected_header):
                                raise ValueError(
                                    f"{label}, row {line_number}: expected {len(expected_header)} columns, got {len(row)}"
                                )
                            timestamp = row[0].strip()
                            if not timestamp:
                                raise ValueError(f"{label}, row {line_number}: missing open_time")
                            if timestamp in seen_times:
                                duplicates += 1
                                continue
                            seen_times.add(timestamp)
                            writer.writerow(row)
                            rows_written += 1

        if rows_written == 0:
            raise ValueError("No data rows were found")
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return rows_written, duplicates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Combine Binance kline ZIP/CSV files into a single CSV."
    )
    parser.add_argument(
        "folder", type=Path, nargs="?",
        help="Folder containing Binance ZIP/CSV files (opens a folder picker when omitted)",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("data/binance_ohlcv.csv"),
        help="Output CSV (default: data/binance_ohlcv.csv)",
    )
    return parser


def run_folder_picker() -> int:
    """Run the easy double-click workflow using native Windows dialogs."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError:
        print("Enter the folder containing the Binance ZIP files:")
        folder_text = input("> ").strip().strip('"')
        if not folder_text:
            return 0
        output_text = input(
            "Output file (press Enter for combined_binance_data.csv in that folder):\n> "
        ).strip().strip('"')
        folder = Path(folder_text)
        output = Path(output_text) if output_text else folder / "combined_binance_data.csv"
        try:
            rows, duplicates = combine(folder, output)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            print(f"Error: {error}", file=sys.stderr)
            return 1
        print(f"Combined {rows:,} rows into {output.resolve()}")
        print(f"Skipped {duplicates:,} duplicate timestamp row(s)")
        return 0

    root = tk.Tk()
    root.withdraw()
    folder_text = filedialog.askdirectory(
        title="Select the folder containing Binance ZIP files"
    )
    if not folder_text:
        root.destroy()
        return 0

    output_text = filedialog.asksaveasfilename(
        title="Save the combined Binance CSV",
        initialdir=folder_text,
        initialfile="combined_binance_data.csv",
        defaultextension=".csv",
        filetypes=[("CSV files", "*.csv")],
    )
    if not output_text:
        root.destroy()
        return 0

    try:
        rows, duplicates = combine(Path(folder_text), Path(output_text))
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        messagebox.showerror("Binance Data Combiner", str(error), parent=root)
        root.destroy()
        return 1

    detail = f"\n\nSkipped {duplicates:,} duplicate timestamp row(s)." if duplicates else ""
    messagebox.showinfo(
        "Binance Data Combiner",
        f"Finished combining {rows:,} rows.\n\nSaved to:\n{Path(output_text).resolve()}{detail}",
        parent=root,
    )
    root.destroy()
    return 0


def main() -> int:
    args = build_parser().parse_args()
    if args.folder is None:
        return run_folder_picker()
    try:
        rows, duplicates = combine(args.folder, args.output)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Combined {rows:,} rows into {args.output.resolve()}")
    if duplicates:
        print(f"Skipped {duplicates:,} duplicate timestamp row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
