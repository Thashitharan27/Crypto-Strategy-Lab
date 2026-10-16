"""Read-only local parity check for existing saved native-v3 configurations.

Usage:
  python -m crypto_strategy_lab.browser_saved_config_parity PATH_TO_CONFIG.json

Prints hashes and never emits configuration values or authentication tokens.
Only the existing validated reader and serializer own config semantics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from pathlib import Path

from crypto_strategy_lab.browser_config import read_research_config
from crypto_strategy_lab.data_lake_config import load_data_lake_config


def _digest(value: dict) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def check(path: Path) -> dict:
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    native = load_data_lake_config(path)
    native.validate()
    expected = native.to_dict()
    projected = read_research_config(path)
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {
        "file": path.name,
        "native_sha256": _digest(expected),
        "browser_reader_sha256": _digest(projected),
        "source_unchanged": before == after,
        "exact_match": expected == projected,
    }
    result["pass"] = result["source_unchanged"] and result["exact_match"]
    return result



def check_http(path: Path) -> dict:
    """Compare an original saved config with the real authenticated API route.

    TestClient keeps HTTP local and in-process; no browser server or market-data
    catalog is started, and no saved config is written.
    """
    from fastapi.testclient import TestClient
    from crypto_strategy_lab.browser_http import create_browser_app
    from crypto_strategy_lab.browser_readonly_service import BrowserReadOnlyService

    if not path.is_file() or path.suffix.lower() != ".json":
        raise ValueError("Saved configuration must be a JSON file")
    if not (1 <= len(path.stem) <= 100 and path.stem.isascii()
            and all(ch.isalnum() or ch in "_-" for ch in path.stem)):
        raise ValueError("Saved config filename is not an allowed browser ID")
    original_bytes = path.read_bytes()
    native = read_research_config(path)
    token = secrets.token_urlsafe(48)
    app = create_browser_app(
        token=token, read_service=BrowserReadOnlyService(None), config_root=path.parent,
    )
    with TestClient(app, base_url="http://localhost") as client:
        headers = {"Authorization": "Bearer " + token}
        denied = client.get(f"/api/v1/configs/{path.stem}")
        response = client.get(f"/api/v1/configs/{path.stem}", headers=headers)
    if denied.status_code != 401 or response.status_code != 200:
        raise ValueError("Config endpoint authentication or lookup failed")
    payload = response.json()
    if not isinstance(payload, dict) or set(payload) != {"config"} or not isinstance(payload["config"], dict):
        raise ValueError("Unexpected browser config response")
    projected = payload["config"]
    source_unchanged = path.read_bytes() == original_bytes
    return {
        "file": path.name,
        "native_sha256": _digest(native),
        "browser_http_sha256": _digest(projected),
        "source_unchanged": source_unchanged,
        "auth_rejected": denied.status_code == 401,
        "exact_match": type(native) is type(projected) and native == projected,
        "pass": source_unchanged and native == projected,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http", action="store_true", help="Also verify actual authenticated read-only HTTP route in-process")
    parser.add_argument("configs", nargs="+", type=Path, help="Existing native v3 JSON configuration paths")
    args = parser.parse_args(argv)
    all_pass = True
    for path in args.configs:
        try:
            result = check_http(path.resolve(strict=True)) if args.http else check(path.resolve(strict=True))
            print(json.dumps(result, sort_keys=True))
            all_pass = all_pass and result["pass"]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            print(json.dumps({"file": path.name, "pass": False, "error_type": type(exc).__name__}))
            all_pass = False
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
