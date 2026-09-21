import sys
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QProcess, QSettings

from crypto_strategy_lab.gui.chatgpt_connection import (
    DEFAULT_MCP_PORT,
    SECONDARY_MCP_PORT,
    TERTIARY_MCP_PORT,
    MCP_MODULE,
    ChatGPTConnectionManager,
    ChatGPTIntegrationWidget,
    TUNNEL_ARGUMENTS,
    redact_secrets,
    tunnel_environment,
    validate_configuration,
)


class FakeProcess:
    def __init__(self, name, events, graceful=True):
        self.name = name
        self.events = events
        self.running = True
        self.graceful = graceful
        self.terminate = Mock(side_effect=self._terminate)
        self.kill = Mock(side_effect=self._kill)
        self.waitForFinished = Mock(side_effect=self._wait)

    def state(self):
        return QProcess.Running if self.running else QProcess.NotRunning

    def _terminate(self):
        self.events.append(f"terminate {self.name}")

    def _kill(self):
        self.events.append(f"kill {self.name}")
        self.running = False

    def _wait(self, _timeout):
        self.events.append(f"wait {self.name}")
        if self.graceful:
            self.running = False
        return not self.running


def test_validation_reports_each_missing_item(tmp_path):
    with patch(
        "crypto_strategy_lab.gui.chatgpt_connection.importlib.util.find_spec",
        return_value=object(),
    ):
        errors = validate_configuration(
            str(tmp_path / "missing.exe"), "", None, tmp_path / "missing-output", 0
        )
    for phrase in ("executable", "Tunnel ID", "API key", "output directory", "port"):
        assert any(phrase in error for error in errors)


def test_valid_configuration(tmp_path):
    exe = tmp_path / "tunnel client.exe"
    exe.touch()
    out = tmp_path / "output"
    out.mkdir()
    with patch(
        "crypto_strategy_lab.gui.chatgpt_connection.importlib.util.find_spec",
        return_value=object(),
    ):
        assert validate_configuration(
            str(exe), "tunnel_example", "secret", out, DEFAULT_MCP_PORT
        ) == []


def test_redaction():
    text = redact_secrets(
        "sk-exampleSecret123 CONTROL_PLANE_API_KEY=another-secret"
    )
    assert "exampleSecret" not in text and "another-secret" not in text
    assert text.count("[REDACTED]") == 2


def test_tunnel_command_and_environment_do_not_mix_secret():
    secret = "super-secret-value"
    env = tunnel_environment(
        secret, "tunnel_example", f"http://127.0.0.1:{DEFAULT_MCP_PORT}/mcp"
    )
    assert TUNNEL_ARGUMENTS == ["run", "--log.level=info", "--log.format=struct-text"]
    assert secret not in TUNNEL_ARGUMENTS
    assert env.value("CONTROL_PLANE_API_KEY") == secret
    assert env.value("CONTROL_PLANE_TUNNEL_ID") == "tunnel_example"
    assert env.value("MCP_SERVER_URL").endswith("/mcp")


def test_widget_exposes_three_independent_chatgpt_connections(qapp, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    output = tmp_path / "output"
    output.mkdir()
    fake_keyring = Mock()
    fake_keyring.get_password.return_value = None

    with patch(
        "crypto_strategy_lab.gui.chatgpt_connection_impl.importlib.import_module",
        return_value=fake_keyring,
    ):
        widget = ChatGPTIntegrationWidget(settings, lambda: str(output))

    try:
        assert widget.manager is not widget.secondary_manager
        assert widget.manager is not widget.tertiary_manager
        assert widget.secondary_manager is not widget.tertiary_manager
        assert widget.port.value() == DEFAULT_MCP_PORT
        assert widget.port2.value() == SECONDARY_MCP_PORT
        assert widget.port3.value() == TERTIARY_MCP_PORT
        assert widget.endpoint.text().endswith(f":{DEFAULT_MCP_PORT}/mcp")
        assert widget.endpoint2.text().endswith(f":{SECONDARY_MCP_PORT}/mcp")
        assert widget.endpoint3.text().endswith(f":{TERTIARY_MCP_PORT}/mcp")
    finally:
        widget.shutdown()


def test_widget_restores_secondary_settings_without_primary_load_overwriting_them(qapp, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setValue("tunnel_id_2", "tunnel_saved_two")
    settings.setValue("mcp_port_2", 8877)
    settings.setValue("auto_start_chatgpt_connection_2", True)
    settings.sync()
    output = tmp_path / "output"
    output.mkdir()
    fake_keyring = Mock()
    fake_keyring.get_password.return_value = None

    with patch(
        "crypto_strategy_lab.gui.chatgpt_connection_impl.importlib.import_module",
        return_value=fake_keyring,
    ):
        widget = ChatGPTIntegrationWidget(settings, lambda: str(output))

    try:
        assert widget.tunnel_id2.text() == "tunnel_saved_two"
        assert widget.port2.value() == 8877
        assert widget.auto_start2.isChecked() is True
    finally:
        widget.shutdown()


def test_widget_restores_tertiary_settings(qapp, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setValue("tunnel_id_3", "tunnel_saved_three")
    settings.setValue("mcp_port_3", 8878)
    settings.setValue("auto_start_chatgpt_connection_3", True)
    settings.sync()
    output = tmp_path / "output"
    output.mkdir()
    fake_keyring = Mock()
    fake_keyring.get_password.return_value = None

    with patch(
        "crypto_strategy_lab.gui.chatgpt_connection_impl.importlib.import_module",
        return_value=fake_keyring,
    ):
        widget = ChatGPTIntegrationWidget(settings, lambda: str(output))

    try:
        assert widget.tunnel_id3.text() == "tunnel_saved_three"
        assert widget.port3.value() == 8878
        assert widget.auto_start3.isChecked() is True
    finally:
        widget.shutdown()


def test_secondary_connection_rejects_primary_port(qapp, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    output = tmp_path / "output"
    output.mkdir()
    fake_keyring = Mock()
    fake_keyring.get_password.return_value = "secret"

    with patch(
        "crypto_strategy_lab.gui.chatgpt_connection_impl.importlib.import_module",
        return_value=fake_keyring,
    ):
        widget = ChatGPTIntegrationWidget(settings, lambda: str(output))

    try:
        exe = tmp_path / "tunnel-client.exe"
        exe.touch()
        widget.path.setText(str(exe))
        widget.tunnel_id2.setText("tunnel_two")
        widget.port2.setValue(widget.port.value())
        with patch(
            "crypto_strategy_lab.gui.chatgpt_connection_impl.importlib.util.find_spec",
            return_value=object(),
        ):
            _key, errors = widget._validated_secondary()
        assert any("different from Connection 1" in error for error in errors)
    finally:
        widget.shutdown()


def test_tertiary_connection_rejects_existing_port_and_tunnel_id(qapp, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    output = tmp_path / "output"
    output.mkdir()
    fake_keyring = Mock()
    fake_keyring.get_password.return_value = "secret"

    with patch(
        "crypto_strategy_lab.gui.chatgpt_connection_impl.importlib.import_module",
        return_value=fake_keyring,
    ):
        widget = ChatGPTIntegrationWidget(settings, lambda: str(output))

    try:
        exe = tmp_path / "tunnel-client.exe"
        exe.touch()
        widget.path.setText(str(exe))
        widget.tunnel_id.setText("tunnel_one")
        widget.tunnel_id2.setText("tunnel_two")
        widget.tunnel_id3.setText("tunnel_two")
        widget.port3.setValue(widget.port2.value())
        with patch(
            "crypto_strategy_lab.gui.chatgpt_connection_impl.importlib.util.find_spec",
            return_value=object(),
        ):
            _key, errors = widget._validated_tertiary()
        assert any("different from Connections 1 and 2" in error for error in errors)
        assert any("Tunnel ID" in error for error in errors)
    finally:
        widget.shutdown()


def test_widget_shutdown_stops_all_three_owned_connections(qapp, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    output = tmp_path / "output"
    output.mkdir()
    fake_keyring = Mock()
    fake_keyring.get_password.return_value = None

    with patch(
        "crypto_strategy_lab.gui.chatgpt_connection_impl.importlib.import_module",
        return_value=fake_keyring,
    ):
        widget = ChatGPTIntegrationWidget(settings, lambda: str(output))

    events = []
    for label, manager in (
        ("one", widget.manager),
        ("two", widget.secondary_manager),
        ("three", widget.tertiary_manager),
    ):
        manager.tunnel = FakeProcess(f"tunnel {label}", events)
        manager.mcp = FakeProcess(f"mcp {label}", events)
        manager._tunnel_started = manager._mcp_started = True

    widget.shutdown()

    assert events == [
        "terminate tunnel three",
        "wait tunnel three",
        "terminate mcp three",
        "wait mcp three",
        "terminate tunnel two",
        "wait tunnel two",
        "terminate mcp two",
        "wait mcp two",
        "terminate tunnel one",
        "wait tunnel one",
        "terminate mcp one",
        "wait mcp one",
    ]


def test_duplicate_start_and_stop_without_processes(qapp, tmp_path):
    manager = ChatGPTConnectionManager(lambda: str(tmp_path))
    manager._starting = True
    assert manager.start("client.exe", "tunnel", "key", DEFAULT_MCP_PORT) is False
    manager._starting = False
    manager.stop()
    assert manager.state == "Disconnected"


def test_shutdown_stops_owned_tunnel_before_owned_mcp(qapp, tmp_path):
    manager = ChatGPTConnectionManager(lambda: str(tmp_path))
    events = []
    manager.tunnel = FakeProcess("tunnel", events)
    manager.mcp = FakeProcess("mcp", events)
    manager._tunnel_started = manager._mcp_started = True

    manager.stop()

    assert events == ["terminate tunnel", "wait tunnel", "terminate mcp", "wait mcp"]
    assert manager.tunnel.state() == manager.mcp.state() == QProcess.NotRunning


def test_shutdown_kills_owned_child_after_graceful_timeout(qapp, tmp_path):
    manager = ChatGPTConnectionManager(lambda: str(tmp_path))
    events = []
    manager.tunnel = FakeProcess("tunnel", events, graceful=False)
    manager.mcp = FakeProcess("mcp", events, graceful=False)
    manager._tunnel_started = manager._mcp_started = True

    manager.stop()

    assert events == [
        "terminate tunnel",
        "wait tunnel",
        "kill tunnel",
        "wait tunnel",
        "terminate mcp",
        "wait mcp",
        "kill mcp",
        "wait mcp",
    ]
    assert manager.tunnel.state() == manager.mcp.state() == QProcess.NotRunning


def test_shutdown_does_not_touch_unowned_processes_or_occupied_port(qapp, tmp_path):
    manager = ChatGPTConnectionManager(lambda: str(tmp_path))
    events = []
    manager.tunnel = FakeProcess("external tunnel", events)
    manager.mcp = FakeProcess("external mcp", events)
    manager._reachable = Mock(return_value=True)

    manager.stop()

    assert events == []
    manager._reachable.assert_called()


def test_repeated_widget_shutdown_is_safe(qapp, tmp_path):
    events = []
    managers = []
    for label in ("one", "two", "three"):
        manager = ChatGPTConnectionManager(lambda: str(tmp_path))
        manager.tunnel = FakeProcess(f"tunnel {label}", events)
        manager.mcp = FakeProcess(f"mcp {label}", events)
        manager._tunnel_started = manager._mcp_started = True
        managers.append(manager)
    widget = Mock(
        manager=managers[0],
        secondary_manager=managers[1],
        tertiary_manager=managers[2],
    )

    ChatGPTIntegrationWidget.shutdown(widget)
    ChatGPTIntegrationWidget.shutdown(widget)

    assert events == [
        "terminate tunnel three", "wait tunnel three",
        "terminate mcp three", "wait mcp three",
        "terminate tunnel two", "wait tunnel two",
        "terminate mcp two", "wait mcp two",
        "terminate tunnel one", "wait tunnel one",
        "terminate mcp one", "wait mcp one",
    ]


def test_main_window_close_shuts_down_chatgpt_widget():
    from crypto_strategy_lab.gui.main_window import MainWindow

    window = Mock(chatgpt_tab=Mock())
    event = Mock()

    MainWindow.closeEvent(window, event)

    window.chatgpt_tab.shutdown.assert_called_once_with()
    event.accept.assert_called_once_with()


def test_clean_shutdown_allows_next_start_without_false_port_conflict(qapp, tmp_path):
    manager = ChatGPTConnectionManager(lambda: str(tmp_path))
    events = []
    manager.tunnel = FakeProcess("tunnel", events)
    manager.mcp = FakeProcess("mcp", events)
    manager._tunnel_started = manager._mcp_started = True
    manager.stop()
    replacement_mcp = Mock()
    replacement_mcp.state.return_value = QProcess.NotRunning
    manager.mcp = replacement_mcp

    with patch.object(manager, "_reachable", return_value=False):
        assert manager.start(
            "client.exe", "tunnel", "key", DEFAULT_MCP_PORT
        ) is True

    replacement_mcp.start.assert_called_once_with(
        sys.executable, ["-m", MCP_MODULE]
    )
    environment = replacement_mcp.setProcessEnvironment.call_args.args[0]
    assert environment.value("CRYPTO_STRATEGY_LAB_ENABLE_CONTROL") == "1"
    assert (
        environment.value("CRYPTO_STRATEGY_LAB_CONTROL_MCP_PORT")
        == str(DEFAULT_MCP_PORT)
    )
    assert environment.value("CRYPTO_STRATEGY_LAB_OUTPUT_DIR") == str(
        tmp_path.resolve()
    )


def test_tunnel_process_error_is_exposed_without_stopping_owned_mcp(qapp, tmp_path):
    manager = ChatGPTConnectionManager(lambda: str(tmp_path))
    manager._starting = True
    manager._mcp_started = True
    manager._tunnel_started = True
    process = Mock()
    process.errorString.return_value = "another tunnel instance is already active"

    with patch.object(manager, "_emit") as emit:
        manager._process_error("Tunnel", process, QProcess.FailedToStart)

    assert manager.state == "Error"
    assert manager._starting is False
    assert manager._mcp_started is True
    assert "another tunnel instance is already active" in manager.last_diagnostic
    assert any(
        "another tunnel instance is already active" in line for line in manager.logs
    )
    emit.assert_called_once_with()


def test_unexpected_tunnel_exit_records_exit_code_and_status(qapp, tmp_path):
    manager = ChatGPTConnectionManager(lambda: str(tmp_path))
    manager._starting = True
    manager._mcp_started = True
    manager._tunnel_started = True

    with patch.object(manager, "_read"), patch.object(manager, "_emit"):
        manager._child_finished("Tunnel", 17, QProcess.CrashExit)

    assert manager.state == "Error"
    assert manager._tunnel_started is False
    assert manager._mcp_started is True
    assert "code 17 (CrashExit)" in manager.last_diagnostic
    assert any("code 17 (CrashExit)" in line for line in manager.logs)


def test_api_key_is_not_a_settings_key(tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    for key, value in {
        "tunnel_client_path": "client.exe",
        "tunnel_id": "tunnel_x",
        "mcp_port": DEFAULT_MCP_PORT,
        "auto_start_chatgpt_connection": True,
        "tunnel_id_2": "tunnel_y",
        "mcp_port_2": SECONDARY_MCP_PORT,
        "auto_start_chatgpt_connection_2": True,
        "tunnel_id_3": "tunnel_z",
        "mcp_port_3": TERTIARY_MCP_PORT,
        "auto_start_chatgpt_connection_3": True,
    }.items():
        settings.setValue(key, value)
    settings.sync()
    assert not any(
        "api" in key.lower() or "credential" in key.lower()
        for key in settings.allKeys()
    )
    assert "secret" not in Path(settings.fileName()).read_text()
