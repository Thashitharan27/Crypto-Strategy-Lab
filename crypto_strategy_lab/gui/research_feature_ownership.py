"""Final GUI composition for research-only evidence ownership.

Research-only controls belong on Research Features. Strategy Builder should show
only permissions and rules that can change trading decisions. The Mean Reversion
toggle remains the existing StrategyConfig field for runtime compatibility; this
module only moves its researcher-facing widget to the correct page.
"""
from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel


def _page_with_title(window, title: str):
    pages = getattr(window, "pages", None)
    if pages is None:
        return None
    for index in range(pages.count()):
        page = pages.widget(index)
        if any(label.text() == title for label in page.findChildren(QLabel)):
            return page
    return None


def apply_research_feature_ownership(window) -> None:
    """Move research-only MR context from Strategy Builder to Research Features."""
    builder = getattr(window, "rule_builder", None)
    if builder is None or not hasattr(builder, "enable_mr"):
        return
    if getattr(window, "mean_reversion_research_box", None) is not None:
        return

    feature_page = _page_with_title(window, "Research Features")
    if feature_page is None or feature_page.layout() is None:
        return

    mr_box = QGroupBox("Mean Reversion Research")
    row = QHBoxLayout(mr_box)
    builder.enable_mr.setText("Attach Mean Reversion context")
    row.addWidget(builder.enable_mr)
    note = QLabel(
        "Research-only context. It does not affect entries or veto trades by itself; "
        "Strategy Builder is reserved for explicit trade-affecting rules."
    )
    note.setWordWrap(True)
    note.setStyleSheet("color:#52606d")
    row.addWidget(note, 1)

    # Insert directly below the Research Features page heading and above the
    # calculation-settings scroll area.
    feature_page.layout().insertWidget(1, mr_box)
    window.mean_reversion_research_box = mr_box

    # The old compatibility container no longer belongs on Strategy Builder.
    for box in builder.findChildren(QGroupBox):
        if box.title() == "4. Research-only Evidence":
            box.hide()
            break

    advanced = getattr(builder, "advanced", None)
    if isinstance(advanced, QGroupBox):
        advanced.setTitle("4. Advanced")
