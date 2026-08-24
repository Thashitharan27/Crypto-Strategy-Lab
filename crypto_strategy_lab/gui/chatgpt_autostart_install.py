"""Install the ChatGPT/MCP connection lifecycle into the composed v3 GUI."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from crypto_strategy_lab.gui.chatgpt_connection import ChatGPTIntegrationWidget


_AUTOSTART_MIGRATION_KEY = "chatgpt_auto_start_default_v1"
_AUTOSTART_SETTING_KEY = "auto_start_chatgpt_connection"


def _setting_is_true(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _apply_default_once(widget: ChatGPTIntegrationWidget) -> None:
    """Adopt auto-start as the default once, then preserve the user's choice."""
    settings = widget.settings
    if _setting_is_true(settings.value(_AUTOSTART_MIGRATION_KEY, False)):
        return

    widget.auto_start.blockSignals(True)
    try:
        widget.auto_start.setChecked(True)
    finally:
        widget.auto_start.blockSignals(False)
    settings.setValue(_AUTOSTART_SETTING_KEY, True)
    settings.setValue(_AUTOSTART_MIGRATION_KEY, True)
    settings.sync()


def _auto_start_if_ready(widget: ChatGPTIntegrationWidget) -> None:
    """Start silently only when the saved connection configuration is usable."""
    if not widget.auto_start.isChecked():
        return
    _key, errors = widget._validated()
    if errors:
        widget.manager._log(
            "GUI",
            "Automatic ChatGPT connection skipped because configuration is incomplete.",
        )
        return
    widget.start()


def apply_chatgpt_autostart(window) -> None:
    """Make the current v3 ChatGPT widget default-on and lifecycle-aware."""
    if getattr(window, "_chatgpt_autostart_installed", False):
        return

    widget = window.findChild(ChatGPTIntegrationWidget)
    if widget is None:
        raise RuntimeError("Active GUI does not contain the ChatGPT integration widget")

    _apply_default_once(widget)

    original_post_show = window.start_post_show_tasks

    def start_post_show_tasks() -> None:
        original_post_show()
        QTimer.singleShot(0, lambda: _auto_start_if_ready(widget))

    window.start_post_show_tasks = start_post_show_tasks
    window.chatgpt_integration = widget

    app = QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(widget.shutdown)

    window._chatgpt_autostart_installed = True
