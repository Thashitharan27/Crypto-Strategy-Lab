"""OpenAI API credential settings for the desktop GUI.

The API key is intentionally kept outside ResearchRunConfig and all run artifacts.
Persistent storage uses the operating-system credential vault via ``keyring``.
"""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from crypto_strategy_lab.ai_decision import AI_MODEL
from crypto_strategy_lab.openai_credentials import (
    activate_openai_api_key,
    openai_api_key_status,
    remove_saved_openai_api_key,
    save_openai_api_key,
)


OPENAI_API_KEYS_URL = "https://platform.openai.com/api-keys"
OPENAI_USAGE_URL = "https://platform.openai.com/usage"


def test_openai_api_key(value: str | None = None) -> dict[str, object]:
    """Authenticate with the Models endpoint; this does not generate model output."""
    key = str(value or "").strip() or activate_openai_api_key()
    if not key:
        return {"ok": False, "message": "No OpenAI API key is configured."}
    try:
        from openai import OpenAI
    except ImportError:
        return {
            "ok": False,
            "message": "OpenAI Python SDK is not installed. Install project requirements first.",
        }

    try:
        models = OpenAI(api_key=key).models.list()
        ids = {
            str(getattr(model, "id", ""))
            for model in getattr(models, "data", ())
            if getattr(model, "id", None)
        }
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code == 401:
            return {"ok": False, "message": "Authentication failed: the API key was rejected."}
        if status_code == 403:
            return {
                "ok": True,
                "warning": True,
                "message": (
                    "The key authenticated, but this project restricts model-list access. "
                    "The strategy can still work if Responses and Batch permissions are enabled."
                ),
            }
        return {"ok": False, "message": f"OpenAI connection failed: {exc}"}

    if ids and AI_MODEL not in ids:
        return {
            "ok": True,
            "warning": True,
            "message": (
                f"API authentication succeeded, but default model {AI_MODEL} was not listed "
                "for this project. Check project/model permissions before generating decisions."
            ),
        }
    return {
        "ok": True,
        "warning": False,
        "message": f"OpenAI API connected. Default model {AI_MODEL} is available.",
    }


class OpenAIAPISettingsWidget(QWidget):
    """GUI page for safely configuring the OpenAI API credential."""

    def __init__(self, parent=None):
        super().__init__(parent)
        activate_openai_api_key()

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Crypto Strategy Lab uses a separately billed OpenAI API key for AI Decision. "
            "The key is never written into strategy JSON, run configuration, cache rows, or reports."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(
            "background:#eef5fb; padding:10px; border:1px solid #c8d9e8"
        )
        layout.addWidget(intro)

        credential_box = QGroupBox("OpenAI API Credential")
        credential_layout = QVBoxLayout(credential_box)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        credential_layout.addWidget(self.status_label)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("API key"))
        self.key_input = QLineEdit()
        self.key_input.setObjectName("openai_api_key_input")
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setPlaceholderText("Paste a new OpenAI API key to save or test")
        self.key_input.setClearButtonEnabled(True)
        key_row.addWidget(self.key_input, 1)
        self.show_key = QCheckBox("Show while typing")
        self.show_key.toggled.connect(self._set_key_visibility)
        key_row.addWidget(self.show_key)
        credential_layout.addLayout(key_row)

        actions = QHBoxLayout()
        self.save_button = QPushButton("Save API Key")
        self.save_button.clicked.connect(self.save_key)
        self.test_button = QPushButton("Test Connection")
        self.test_button.clicked.connect(self.test_connection)
        self.remove_button = QPushButton("Remove Saved Key")
        self.remove_button.clicked.connect(self.remove_key)
        actions.addWidget(self.save_button)
        actions.addWidget(self.test_button)
        actions.addWidget(self.remove_button)
        actions.addStretch()
        credential_layout.addLayout(actions)

        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        credential_layout.addWidget(self.result_label)
        layout.addWidget(credential_box)

        security_box = QGroupBox("Security / Billing")
        security_layout = QVBoxLayout(security_box)
        security_note = QLabel(
            "Save API Key stores the secret in the operating-system credential vault "
            "(Windows Credential Manager on Windows) and activates OPENAI_API_KEY only inside "
            "the running process. This API billing is separate from ChatGPT Plus. Use an API "
            "Project with a sensible budget and restricted permissions where practical."
        )
        security_note.setWordWrap(True)
        security_layout.addWidget(security_note)

        links = QHBoxLayout()
        keys_button = QPushButton("Open API Keys")
        keys_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(OPENAI_API_KEYS_URL))
        )
        usage_button = QPushButton("Open API Usage")
        usage_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(OPENAI_USAGE_URL))
        )
        links.addWidget(keys_button)
        links.addWidget(usage_button)
        links.addStretch()
        security_layout.addLayout(links)
        layout.addWidget(security_box)

        model_note = QLabel(
            f"Current AI Decision default: {AI_MODEL}. Historical runs remain CACHE_ONLY unless you "
            "explicitly prepare/submit Batch API work."
        )
        model_note.setWordWrap(True)
        model_note.setStyleSheet("color:#52606d; padding:6px")
        layout.addWidget(model_note)
        layout.addStretch()
        self.refresh_status()

    def _set_key_visibility(self, visible: bool) -> None:
        self.key_input.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)

    def refresh_status(self) -> None:
        status = openai_api_key_status()
        if status["configured"]:
            persistence = "saved" if status["persistent"] else "environment/session"
            self.status_label.setText(
                f"Status: Configured ({status['source']}; {persistence})."
            )
            self.status_label.setStyleSheet("font-weight:bold")
        else:
            self.status_label.setText("Status: No OpenAI API key configured.")
            self.status_label.setStyleSheet("font-weight:bold")
        self.remove_button.setEnabled(bool(status["configured"]))

    def save_key(self) -> None:
        try:
            status = save_openai_api_key(self.key_input.text())
        except Exception as exc:
            self.result_label.setText(f"Could not save API key: {exc}")
            return
        self.key_input.clear()
        self.show_key.setChecked(False)
        self.refresh_status()
        if status["persistent"]:
            self.result_label.setText(
                "API key saved securely in the OS credential vault and activated for this app."
            )
        else:
            self.result_label.setText("API key activated for this app session.")

    def remove_key(self) -> None:
        try:
            remove_saved_openai_api_key()
        except Exception as exc:
            self.result_label.setText(f"Could not remove saved API key: {exc}")
            return
        self.key_input.clear()
        self.show_key.setChecked(False)
        self.result_label.setText("Saved OpenAI API key removed from the OS credential vault.")
        self.refresh_status()

    def test_connection(self) -> None:
        candidate = self.key_input.text().strip() or None
        self.result_label.setText("Testing OpenAI API connection…")
        result = test_openai_api_key(candidate)
        self.result_label.setText(str(result["message"]))
