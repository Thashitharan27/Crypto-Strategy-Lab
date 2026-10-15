"""Offline CLI regression tests; never require historical archive access."""
import json

import pytest

from tools.freeze_browser_parity_inputs import main


def test_freeze_verify_and_refuse_overwrite(tmp_path):
    source = tmp_path / "original.zip"
    source.write_bytes(b"immutable test bytes")
    files = tmp_path / "files.json"
    files.write_text(json.dumps({"original_1m": str(source)}), encoding="utf-8")
    manifest = tmp_path / "freeze.json"
    args = ["--files-json", str(files), "--manifest-json", str(manifest)]
    assert main(args + ["--commit-sha", "a" * 40]) == 0
    frozen = json.loads(manifest.read_text(encoding="utf-8"))
    assert frozen["files"]["original_1m"]["bytes"] == len(source.read_bytes())
    assert main(args + ["--verify"]) == 0
    with pytest.raises(SystemExit):
        main(args + ["--commit-sha", "a" * 40])
    source.write_bytes(b"altered bytes")
    with pytest.raises(ValueError, match="mismatch"):
        main(args + ["--verify"])


def test_reject_empty_mapping(tmp_path):
    files = tmp_path / "files.json"
    files.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--files-json", str(files), "--manifest-json",
              str(tmp_path / "freeze.json"), "--commit-sha", "a" * 40])


def test_exclusive_create_blocks_racing_writer(tmp_path, monkeypatch):
    """A competing manifest appearing after the existence check is never replaced."""
    source = tmp_path / "original.zip"
    source.write_bytes(b"source bytes")
    files = tmp_path / "files.json"
    files.write_text(json.dumps({"original": str(source)}), encoding="utf-8")
    manifest = tmp_path / "freeze.json"
    original_verify = __import__(
        "tools.freeze_browser_parity_inputs", fromlist=["verify_frozen_fixture_files"]
    ).verify_frozen_fixture_files

    def competing_writer(expected, paths):
        original_verify(expected, paths)
        manifest.write_text("other writer", encoding="utf-8")

    monkeypatch.setattr(
        "tools.freeze_browser_parity_inputs.verify_frozen_fixture_files",
        competing_writer,
    )
    with pytest.raises(FileExistsError):
        main(["--files-json", str(files), "--manifest-json", str(manifest),
              "--commit-sha", "a" * 40])
    assert manifest.read_text(encoding="utf-8") == "other writer"
