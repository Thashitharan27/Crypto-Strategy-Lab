from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)

from crypto_strategy_lab.data import DataQualityIssue, DataQualityStatus
from crypto_strategy_lab.gui.run_readiness import MainWindow


class _IssueRenderHarness:
    @staticmethod
    def _time_text(value) -> str:
        return str(value)

    @staticmethod
    def _issue_text(issue) -> str:
        return issue.code.replace("_", " ").lower()

    @staticmethod
    def _missing_dataset_line(_report) -> str:
        return "missing dataset detail"


def test_unrecognized_blocking_issue_is_not_hidden_from_readiness():
    issue = DataQualityIssue(
        "CONFLICTING_ARCHIVE_OVERLAP",
        DataQualityStatus.ERROR,
        "Overlapping archives disagree for a logical key",
        count=2,
    )
    lines: list[str] = []

    MainWindow._append_issue_line(_IssueRenderHarness(), lines, issue)

    assert len(lines) == 1
    assert "Overlapping archives disagree for a logical key" in lines[0]
    assert "CONFLICTING_ARCHIVE_OVERLAP" in lines[0]
    assert "2 affected" in lines[0]


def test_unrecognized_warning_does_not_clutter_blocking_readiness():
    issue = DataQualityIssue(
        "IDENTICAL_ARCHIVE_OVERLAP",
        DataQualityStatus.WARN,
        "Overlapping source rows are identical",
        count=2,
    )
    lines: list[str] = []

    MainWindow._append_issue_line(_IssueRenderHarness(), lines, issue)

    assert lines == []
