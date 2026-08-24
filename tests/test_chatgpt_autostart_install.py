from unittest.mock import Mock

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMainWindow

from crypto_strategy_lab.gui.chatgpt_autostart_install import (
    _auto_start_if_ready,
    apply_chatgpt_autostart,
)
from crypto_strategy_lab.gui.chatgpt_connection import ChatGPTIntegrationWidget


def _window_with_chat(tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    window = QMainWindow()
    window.start_post_show_tasks = Mock()
    widget = ChatGPTIntegrationWidget(settings, lambda: str(tmp_path), window)
    return window, widget, settings


def test_autostart_becomes_default_once_then_preserves_opt_out(qapp, tmp_path):
    window, widget, settings = _window_with_chat(tmp_path)
    try:
        assert widget.auto_start.isChecked() is False
        apply_chatgpt_autostart(window)
        assert widget.auto_start.isChecked() is True
        assert settings.value("auto_start_chatgpt_connection", type=bool) is True
        assert settings.value("chatgpt_auto_start_default_v1", type=bool) is True

        widget.auto_start.setChecked(False)
        settings.sync()
        assert settings.value("auto_start_chatgpt_connection", type=bool) is False
    finally:
        window.close()

    second_window, second_widget, _settings = _window_with_chat(tmp_path)
    try:
        apply_chatgpt_autostart(second_window)
        assert second_widget.auto_start.isChecked() is False
    finally:
        second_window.close()


def test_post_show_hook_schedules_current_chat_widget(qapp, tmp_path, monkeypatch):
    window, widget, _settings = _window_with_chat(tmp_path)
    callback = Mock()
    try:
        apply_chatgpt_autostart(window)
        monkeypatch.setattr(
            "crypto_strategy_lab.gui.chatgpt_autostart_install._auto_start_if_ready",
            callback,
        )
        original = window.start_post_show_tasks.__closure__[0].cell_contents
        window.start_post_show_tasks()
        qapp.processEvents()

        original.assert_called_once_with()
        callback.assert_called_once_with(widget)
    finally:
        window.close()


def test_autostart_skips_incomplete_configuration_without_manual_start(qapp, tmp_path):
    window, widget, _settings = _window_with_chat(tmp_path)
    try:
        widget.auto_start.setChecked(True)
        widget._validated = Mock(return_value=(None, ["Tunnel ID is required."]))
        widget.start = Mock()

        _auto_start_if_ready(widget)

        widget.start.assert_not_called()
        assert any(
            "Automatic ChatGPT connection skipped" in line
            for line in widget.manager.logs
        )
    finally:
        window.close()
