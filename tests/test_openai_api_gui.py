"""Safety tests for the OpenAI API credential GUI."""
from __future__ import annotations

import os

import pytest


class _FakeKeyring:
    def __init__(self):
        self.value = None
        self.calls = []

    def get_password(self, service, username):
        self.calls.append(("get", service, username))
        return self.value

    def set_password(self, service, username, value):
        self.calls.append(("set", service, username))
        self.value = value

    def delete_password(self, service, username):
        self.calls.append(("delete", service, username))
        self.value = None


def test_credential_vault_roundtrip_never_returns_secret(monkeypatch):
    from crypto_strategy_lab import openai_credentials as credentials

    fake = _FakeKeyring()
    monkeypatch.setattr(credentials, "_keyring_module", lambda: fake)
    monkeypatch.delenv(credentials.OPENAI_API_KEY_ENV, raising=False)

    secret = "sk-test-secret-value"
    status = credentials.save_openai_api_key(secret)
    assert fake.value == secret
    assert os.environ[credentials.OPENAI_API_KEY_ENV] == secret
    assert status["configured"] is True
    assert status["persistent"] is True
    assert secret not in repr(status)

    status = credentials.remove_saved_openai_api_key()
    assert fake.value is None
    assert credentials.OPENAI_API_KEY_ENV not in os.environ
    assert status["configured"] is False
    assert secret not in repr(status)


def test_explicit_environment_key_takes_precedence_over_saved_key(monkeypatch):
    from crypto_strategy_lab import openai_credentials as credentials

    fake = _FakeKeyring()
    fake.value = "sk-vault-key"
    monkeypatch.setattr(credentials, "_keyring_module", lambda: fake)
    monkeypatch.setenv(credentials.OPENAI_API_KEY_ENV, "sk-environment-key")

    assert credentials.activate_openai_api_key() == "sk-environment-key"
    status = credentials.openai_api_key_status()
    assert status["source"] == "OPENAI_API_KEY environment variable"
    assert status["persistent"] is False


def _qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    return widgets, widgets.QApplication.instance() or widgets.QApplication([])


def test_api_key_entry_is_password_masked_and_save_clears_field(monkeypatch):
    widgets, _app = _qt_app()
    import crypto_strategy_lab.gui.openai_api_settings as settings

    state = {"configured": False, "source": None, "persistent": False}
    monkeypatch.setattr(settings, "activate_openai_api_key", lambda: None)
    monkeypatch.setattr(settings, "openai_api_key_status", lambda: dict(state))

    def save(value):
        assert value == "sk-example"
        state.update(
            configured=True,
            source="OS credential vault",
            persistent=True,
        )
        return dict(state)

    monkeypatch.setattr(settings, "save_openai_api_key", save)
    widget = settings.OpenAIAPISettingsWidget()
    try:
        assert widget.key_input.echoMode() == widgets.QLineEdit.Password
        widget.key_input.setText("sk-example")
        widget.save_key()
        assert widget.key_input.text() == ""
        assert "OS credential vault" in widget.status_label.text()
        assert "sk-example" not in widget.status_label.text()
        assert "sk-example" not in widget.result_label.text()
    finally:
        widget.close()


def test_ai_generation_toggle_changes_only_current_process_mode(monkeypatch):
    _widgets, _app = _qt_app()
    import crypto_strategy_lab.gui.openai_api_settings as settings

    monkeypatch.setattr(settings, "activate_openai_api_key", lambda: None)
    monkeypatch.setattr(
        settings,
        "openai_api_key_status",
        lambda: {"configured": False, "source": None, "persistent": False},
    )
    monkeypatch.delenv(settings.AI_CACHE_MODE_ENV, raising=False)

    widget = settings.OpenAIAPISettingsWidget()
    try:
        assert settings.current_ai_runtime_mode() == settings.AI_CACHE_ONLY
        assert widget.generate_missing_checkbox.isChecked() is False
        assert "CACHE_ONLY" in widget.mode_status_label.text()

        widget.generate_missing_checkbox.setChecked(True)
        assert os.environ[settings.AI_CACHE_MODE_ENV] == settings.AI_CACHE_THEN_API
        assert settings.current_ai_runtime_mode() == settings.AI_CACHE_THEN_API
        assert "CACHE_THEN_API" in widget.mode_status_label.text()
        assert "paid API calls" in widget.result_label.text()

        widget.generate_missing_checkbox.setChecked(False)
        assert settings.AI_CACHE_MODE_ENV not in os.environ
        assert settings.current_ai_runtime_mode() == settings.AI_CACHE_ONLY
        assert "CACHE_ONLY" in widget.mode_status_label.text()
    finally:
        widget.close()


def test_invalid_runtime_mode_fails_closed(monkeypatch):
    import crypto_strategy_lab.gui.openai_api_settings as settings

    monkeypatch.setenv(settings.AI_CACHE_MODE_ENV, "SOMETHING_UNSAFE")
    assert settings.current_ai_runtime_mode() == settings.AI_CACHE_ONLY
    with pytest.raises(ValueError, match="Unsupported AI runtime mode"):
        settings.set_ai_runtime_mode("SOMETHING_UNSAFE")


def test_connection_without_key_does_not_make_network_call(monkeypatch):
    import crypto_strategy_lab.gui.openai_api_settings as settings

    monkeypatch.setattr(settings, "activate_openai_api_key", lambda: None)
    result = settings.test_openai_api_key(None)
    assert result["ok"] is False
    assert "No OpenAI API key" in result["message"]


def test_installer_adds_openai_api_tool_page(monkeypatch):
    widgets, _app = _qt_app()
    import crypto_strategy_lab.gui.openai_api_settings as settings
    from crypto_strategy_lab.gui.openai_api_install import apply_openai_api_settings
    from crypto_strategy_lab.gui.v2_main_window import MainWindow

    monkeypatch.setattr(settings, "activate_openai_api_key", lambda: None)
    monkeypatch.setattr(
        settings,
        "openai_api_key_status",
        lambda: {"configured": False, "source": None, "persistent": False},
    )

    class Catalog:
        def symbols(self):
            return ["BTCUSDT"]

        def coverage(self, _request):
            return []

        def inventory(self, *_args):
            return []

    class Service:
        catalog = Catalog()

        def refresh_catalog(self):
            return 0

    window = MainWindow(service=Service())
    try:
        before = window.pages.count()
        apply_openai_api_settings(window)
        assert window.pages.count() == before + 1
        assert window.openai_api_nav_button.text() == "OpenAI API"
        window.openai_api_nav_button.click()
        assert window.pages.currentWidget() is window.openai_api_page
        assert isinstance(window.openai_api_settings, settings.OpenAIAPISettingsWidget)

        # Idempotent install must not duplicate the sidebar/page.
        apply_openai_api_settings(window)
        assert window.pages.count() == before + 1
    finally:
        window.close()


def test_desktop_entry_point_installs_openai_api_page():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert "apply_openai_api_settings(window)" in source
