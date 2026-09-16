"""Secure OpenAI API credential handling shared by GUI and CLI entry points.

The preferred persistent store is the operating-system credential vault exposed
through ``keyring`` (Windows Credential Manager on the supported desktop setup).
An explicitly supplied OPENAI_API_KEY environment variable remains supported and
takes precedence, matching OpenAI's standard SDK convention.
"""
from __future__ import annotations

import importlib
import os
from typing import Any


OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
KEYRING_SERVICE = "CryptoStrategyLab.OpenAIAPI"
KEYRING_USERNAME = "openai_api_key"


def _keyring_module():
    try:
        return importlib.import_module("keyring")
    except Exception:
        return None


def _saved_key() -> str | None:
    keyring = _keyring_module()
    if keyring is None:
        return None
    try:
        value = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        return None
    value = str(value or "").strip()
    return value or None


def activate_openai_api_key() -> str | None:
    """Make a stored key available to the existing OpenAI SDK integration.

    An environment key wins over the credential vault. Otherwise a vault key is
    copied only into this process's environment; it is never written to config,
    cache or report files.
    """
    runtime = str(os.environ.get(OPENAI_API_KEY_ENV, "")).strip()
    if runtime:
        return runtime
    saved = _saved_key()
    if saved:
        os.environ[OPENAI_API_KEY_ENV] = saved
        return saved
    return None


def openai_api_key_status() -> dict[str, Any]:
    """Return status metadata without ever returning the secret value."""
    runtime = str(os.environ.get(OPENAI_API_KEY_ENV, "")).strip() or None
    saved = _saved_key()
    if runtime is None and saved:
        os.environ[OPENAI_API_KEY_ENV] = saved
        runtime = saved

    if saved and runtime == saved:
        source = "OS credential vault"
        persistent = True
    elif runtime:
        source = "OPENAI_API_KEY environment variable"
        persistent = False
    elif saved:
        source = "OS credential vault"
        persistent = True
    else:
        source = None
        persistent = False
    return {
        "configured": bool(runtime or saved),
        "source": source,
        "persistent": persistent,
        "keyring_available": _keyring_module() is not None,
    }


def save_openai_api_key(value: str) -> dict[str, Any]:
    """Save the key in the OS credential vault and activate it immediately."""
    key = str(value).strip()
    if not key:
        raise ValueError("Enter an OpenAI API key before saving.")
    if any(character.isspace() for character in key):
        raise ValueError("The API key must not contain whitespace.")

    keyring = _keyring_module()
    if keyring is None:
        raise RuntimeError(
            "The keyring package is unavailable. Install project requirements before saving."
        )
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key)
    except Exception as exc:
        raise RuntimeError(f"Could not store the API key in the OS credential vault: {exc}") from exc

    os.environ[OPENAI_API_KEY_ENV] = key
    return openai_api_key_status()


def remove_saved_openai_api_key() -> dict[str, Any]:
    """Delete the vault entry without erasing an unrelated external env key."""
    saved = _saved_key()
    keyring = _keyring_module()
    if keyring is not None and saved:
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except Exception as exc:
            # Some backends raise when the credential disappeared between read/delete.
            if exc.__class__.__name__ not in {"PasswordDeleteError", "KeyringError"}:
                raise

    runtime = str(os.environ.get(OPENAI_API_KEY_ENV, "")).strip() or None
    if saved and runtime == saved:
        os.environ.pop(OPENAI_API_KEY_ENV, None)
    return openai_api_key_status()
