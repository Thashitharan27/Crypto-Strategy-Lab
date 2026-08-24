"""Controlled relaunch support for desktop updates."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


CREATE_NO_WINDOW = 0x08000000


def application_entrypoint() -> Path:
    """Return the canonical checkout entry point used for desktop relaunch."""
    return Path(__file__).resolve().parents[2] / "app.py"


def replacement_command(
    executable: str | Path | None = None,
    app_path: str | Path | None = None,
) -> list[str]:
    """Build the shell-free command for restarting this exact Python runtime."""
    python = Path(executable or sys.executable).resolve()
    target = Path(app_path or application_entrypoint()).resolve()
    return [str(python), str(target)]


def launch_replacement(
    executable: str | Path | None = None,
    app_path: str | Path | None = None,
):
    """Launch a replacement process after the current Qt event loop has exited."""
    command = replacement_command(executable, app_path)
    target = Path(command[1])
    kwargs = {
        "cwd": str(target.parent),
        "shell": False,
    }
    if os.name == "nt" and Path(command[0]).name.lower() == "pythonw.exe":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return subprocess.Popen(command, **kwargs)
