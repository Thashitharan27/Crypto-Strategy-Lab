"""Install richer current-request data-quality diagnostics in the active GUI.

The validator already records exact missing-candle counts/timestamps/ranges.  The
legacy six-column quality table only surfaced issue codes, which made an internal
coverage failure hard to repair.  This presentation layer exposes the existing
validator facts without changing validation or run semantics.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import MethodType

from PySide6.QtWidgets import QTableWidgetItem


QUALITY_HEADERS = (
    "Role",
    "Symbol",
    "Dataset",
    "Interval",
    "Required",
    "Rows",
    "Status",
    "Missing Candles",
    "First Gap UTC",
    "Last Gap UTC",
    "Issues",
)

_EXACT_CANDLE_GAP_CODES = frozenset(
    {
        "LEADING_COVERAGE_GAP",
        "TRAILING_COVERAGE_GAP",
        "MISSING_INTERNAL_INTERVAL",
    }
)
_COVERAGE_GAP_CODES = frozenset(
    {
        *_EXACT_CANDLE_GAP_CODES,
        "LEADING_SOURCE_COVERAGE_GAP",
        "TRAILING_SOURCE_COVERAGE_GAP",
    }
)


def _dataset_key(value) -> str:
    raw = getattr(value, "value", value)
    text = str(raw).lower()
    return text.split(".", 1)[1] if text.startswith("datasetkind.") else text


def _format_utc(value) -> str:
    if value in (None, ""):
        return "—"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
        return parsed.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError):
        return text


def _role_for_dataset(window, dataset) -> str:
    benchmark_check = getattr(window, "_is_benchmark_report", None)
    if callable(benchmark_check):
        try:
            if benchmark_check(dataset):
                return "Market Regime Benchmark"
        except Exception:
            pass

    interval = getattr(dataset, "interval", None)
    dataset_name = _dataset_key(getattr(dataset, "dataset", ""))
    strategy = getattr(getattr(window, "strategy_tf", None), "currentData", lambda: None)()
    intrabar = getattr(getattr(window, "intrabar_tf", None), "currentData", lambda: None)()
    if dataset_name == "klines":
        if interval == strategy and interval == intrabar:
            return "Strategy + Intrabar / Exits"
        if interval == strategy:
            return "Strategy"
        if intrabar and interval == intrabar:
            return "Intrabar / Exits"
    return "Required Data" if bool(getattr(dataset, "required", False)) else "Optional Research"


def _issue_ranges(issue) -> list[dict]:
    details = getattr(issue, "details", {}) or {}
    ranges = details.get("ranges", ()) if hasattr(details, "get") else ()
    return [item for item in ranges if isinstance(item, dict)]


def _gap_summary(dataset) -> tuple[str, str, str, str]:
    """Return exact missing count, first/last gap and a detailed tooltip."""
    issues = tuple(getattr(dataset, "issues", ()) or ())
    exact = [issue for issue in issues if str(getattr(issue, "code", "")) in _EXACT_CANDLE_GAP_CODES]
    coverage = [issue for issue in issues if str(getattr(issue, "code", "")) in _COVERAGE_GAP_CODES]

    missing_count = sum(max(0, int(getattr(issue, "count", 0) or 0)) for issue in exact)
    missing_text = f"{missing_count:,}" if exact else "—"

    first_values: list[str] = []
    last_values: list[str] = []
    detail_lines: list[str] = []
    for issue in coverage:
        first = getattr(issue, "first_timestamp", None)
        last = getattr(issue, "last_timestamp", None)
        if first:
            first_values.append(str(first))
        if last:
            last_values.append(str(last))
        ranges = _issue_ranges(issue)
        if ranges:
            for item in ranges:
                start = item.get("start")
                end = item.get("end")
                count = item.get("missing_count")
                count_text = f" · {int(count):,} missing" if count is not None else ""
                detail_lines.append(
                    f"{getattr(issue, 'code', 'GAP')}: {_format_utc(start)} → {_format_utc(end)}{count_text}"
                )
        else:
            message = str(getattr(issue, "message", "") or "")
            count = int(getattr(issue, "count", 0) or 0)
            detail = f"{getattr(issue, 'code', 'GAP')}"
            if count:
                detail += f" · {count:,}"
            if message:
                detail += f" · {message}"
            detail_lines.append(detail)

    first_text = _format_utc(min(first_values)) if first_values else "—"
    last_text = _format_utc(max(last_values)) if last_values else "—"
    return missing_text, first_text, last_text, "\n".join(detail_lines)


def _issues_text(dataset) -> str:
    parts = []
    for issue in tuple(getattr(dataset, "issues", ()) or ()):
        code = str(getattr(issue, "code", ""))
        count = int(getattr(issue, "count", 0) or 0)
        parts.append(f"{code} ({count:,})" if count not in (0, 1) else code)
    return "; ".join(parts) or "—"


def _issues_tooltip(dataset, gap_detail: str) -> str:
    lines = []
    if gap_detail:
        lines.append("Gap ranges:")
        lines.extend(f"  {line}" for line in gap_detail.splitlines())
    for issue in tuple(getattr(dataset, "issues", ()) or ()):
        if str(getattr(issue, "code", "")) in _COVERAGE_GAP_CODES:
            continue
        code = str(getattr(issue, "code", ""))
        message = str(getattr(issue, "message", "") or "")
        count = int(getattr(issue, "count", 0) or 0)
        text = code
        if count:
            text += f" · {count:,}"
        if message:
            text += f" · {message}"
        lines.append(text)
    return "\n".join(lines)


def _configure_table(table) -> None:
    table.setColumnCount(len(QUALITY_HEADERS))
    table.setHorizontalHeaderLabels(QUALITY_HEADERS)
    table.setMinimumHeight(max(table.minimumHeight(), 220))
    table.horizontalHeader().setStretchLastSection(True)


def _render_data_quality(self, report) -> None:
    table = self.quality_table
    _configure_table(table)
    if report is None:
        self.quality.setText("Data quality: NOT AVAILABLE")
        table.setRowCount(0)
        return

    status = getattr(getattr(report, "overall_status", None), "value", None)
    self.quality.setText("Data quality: " + str(status or "UNKNOWN"))
    datasets = tuple(getattr(report, "datasets", ()) or ())
    table.setRowCount(len(datasets))

    for row, dataset in enumerate(datasets):
        missing, first_gap, last_gap, gap_detail = _gap_summary(dataset)
        dataset_status = getattr(getattr(dataset, "status", None), "value", getattr(dataset, "status", "—"))
        values = (
            _role_for_dataset(self, dataset),
            getattr(dataset, "symbol", "—") or "—",
            _dataset_key(getattr(dataset, "dataset", "—")),
            getattr(dataset, "interval", None) or "event",
            bool(getattr(dataset, "required", False)),
            f"{int(getattr(dataset, 'row_count', 0) or 0):,}",
            dataset_status,
            missing,
            first_gap,
            last_gap,
            _issues_text(dataset),
        )
        tooltip = _issues_tooltip(dataset, gap_detail)
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if tooltip and column in (7, 8, 9, 10):
                item.setToolTip(tooltip)
            table.setItem(row, column, item)

    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)


def apply_validation_gap_diagnostics(window) -> None:
    """Expose validator gap facts in the active Data Library quality table."""
    if getattr(window, "_validation_gap_diagnostics_installed", False):
        return
    if not hasattr(window, "quality_table") or not hasattr(window, "quality"):
        return

    window._validation_gap_diagnostics_installed = True
    _configure_table(window.quality_table)
    window.render_data_quality = MethodType(_render_data_quality, window)

    report = getattr(window, "_validated_report", None)
    if report is not None:
        window.render_data_quality(report)
