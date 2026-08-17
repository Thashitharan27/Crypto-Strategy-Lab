"""A deliberately small, read-only MCP server for saved backtest output."""
from __future__ import annotations

import csv
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
from openpyxl import load_workbook

LOGGER = logging.getLogger("crypto_strategy_lab.mcp")
SUPPORTED = {".csv", ".xlsx", ".json", ".txt"}
FORBIDDEN_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|COPY|EXPORT|IMPORT|ATTACH|DETACH|"
    r"INSTALL|LOAD|PRAGMA|CALL|SET|RESET|TRUNCATE|VACUUM)\b", re.IGNORECASE
)
ALLOWED_SQL = re.compile(r"^\s*(?:SELECT|WITH|DESCRIBE|SHOW)\b", re.IGNORECASE)
EXTERNAL_SQL = re.compile(
    r"\b(?:read_csv(?:_auto)?|read_json(?:_auto)?|read_parquet|read_text|glob|"
    r"sqlite_scan|postgres_scan|mysql_scan|delta_scan|iceberg_scan)\s*\(|"
    r"\b(?:FROM|JOIN)\s*['\"]",
    re.IGNORECASE,
)


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, Path)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if hasattr(value, "item"):
        return value.item()
    return value


class BacktestReports:
    """Validated access to one output root; every operation is read-only."""

    def __init__(self, output_root: str | Path):
        root = Path(output_root).expanduser()
        if not root.is_dir():
            raise ValueError(f"Output directory does not exist: {root}")
        self.root = root.resolve(strict=True)

    def _inside(self, path: Path) -> bool:
        return path == self.root or self.root in path.parents

    def _resolve(self, relative: str | Path, *, directory: bool | None = None) -> Path:
        raw = Path(relative)
        if raw.is_absolute():
            raise ValueError("Absolute paths are not allowed")
        if not raw.parts or any(part == ".." for part in raw.parts):
            raise ValueError("Path traversal is not allowed")
        try:
            resolved = (self.root / raw).resolve(strict=True)
        except (FileNotFoundError, RuntimeError) as exc:
            raise ValueError(f"Path does not exist: {relative}") from exc
        if not self._inside(resolved):
            raise ValueError("Resolved path is outside the allowed output root")
        if directory is True and not resolved.is_dir():
            raise ValueError("Run is not a directory")
        if directory is False and not resolved.is_file():
            raise ValueError("Report is not a file")
        return resolved

    def resolve_run(self, run: str) -> Path:
        path = self._resolve(run, directory=True)
        if path.parent != self.root:
            raise ValueError("Run must be a direct child of the output root")
        return path

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _pick(sources: list[dict[str, Any]], *names: str) -> Any:
        normalized = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for source in sources for k, v in source.items()}
        for name in names:
            value = normalized.get(re.sub(r"[^a-z0-9]", "", name.lower()))
            if value is not None:
                return value
        return None

    def _metadata(self, run: Path) -> dict[str, Any]:
        config = self._load_json(run / "config.json") if (run / "config.json").is_file() else {}
        summary = self._load_json(run / "summary.json") if (run / "summary.json").is_file() else {}
        sources = [summary, config]
        return {
            "run_name": self._pick(sources, "run_name") or run.name,
            "folder_name": run.name,
            "modified_time": _iso(run.stat().st_mtime),
            "symbol": self._pick(sources, "symbol", "ticker"),
            "strategy_timeframe": self._pick(sources, "strategy_timeframe", "strategy_timeframe_minutes", "timeframe"),
            "risk_mode": self._pick(sources, "risk_mode"),
            "atr_period": self._pick(sources, "atr_period"),
            "atr_multiplier": self._pick(sources, "atr_multiplier"),
            "trade_count": self._pick(sources, "trade_count", "total_trades", "trades"),
        }

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        runs = [p for p in self.root.iterdir() if p.is_dir() and not p.is_symlink()]
        runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [self._metadata(run) for run in runs[:limit]]

    def latest_run(self) -> dict[str, Any]:
        runs = self.list_runs(1)
        if not runs:
            raise ValueError("No completed backtest runs were found")
        run = self.resolve_run(runs[0]["folder_name"])
        result = {**runs[0], "path": run.name, "available_files": [x["filename"] for x in self.list_run_files(run.name)]}
        if (run / "summary.json").is_file():
            result["summary"] = self._load_json(run / "summary.json")
        return result

    def list_run_files(self, run: str) -> list[dict[str, Any]]:
        folder = self.resolve_run(run)
        result = []
        for path in folder.rglob("*"):
            if len(result) >= 2000:
                break
            if path.is_file() and not path.is_symlink() and self._inside(path.resolve()):
                stat = path.stat()
                result.append({"filename": path.relative_to(folder).as_posix(), "extension": path.suffix.lower(), "size": stat.st_size, "modified_time": _iso(stat.st_mtime)})
        return sorted(result, key=lambda item: item["filename"].lower())

    def _report_path(self, run: str, filename: str) -> Path:
        folder = self.resolve_run(run)
        path = self._resolve(Path(run) / filename, directory=False)
        if folder not in path.parents or path.suffix.lower() not in SUPPORTED:
            raise ValueError("Unsupported report path or file type")
        return path

    def read_report(self, run: str, filename: str, sheet: str | None = None, limit: int = 200) -> dict[str, Any]:
        if not 1 <= limit <= 5000:
            raise ValueError("limit must be between 1 and 5000")
        path = self._report_path(run, filename)
        suffix = path.suffix.lower()
        if suffix == ".json":
            return {"type": "json", "data": json.loads(path.read_text(encoding="utf-8-sig"))}
        if suffix == ".txt":
            with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
                text = handle.read(1_000_001)
            return {"type": "text", "text": text[:1_000_000], "truncated": len(text) > 1_000_000}
        if suffix == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                columns = next(reader, [])
                rows, total = [], 0
                for row in reader:
                    total += 1
                    if len(rows) < limit:
                        rows.append(row)
            return {"type": "table", "columns": columns, "rows": rows, "row_count": total, "truncated": total > limit}
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            if sheet is not None and sheet not in workbook.sheetnames:
                raise ValueError(f"Unknown sheet; available sheets: {workbook.sheetnames}")
            ws = workbook[sheet] if sheet else workbook[workbook.sheetnames[0]]
            iterator = ws.iter_rows(values_only=True)
            columns = [str(v) if v is not None else "" for v in next(iterator, ())]
            rows, total = [], 0
            for row in iterator:
                total += 1
                if len(rows) < limit:
                    rows.append([_json_value(v) for v in row])
            return {"type": "table", "sheet": ws.title, "available_sheets": workbook.sheetnames, "columns": columns, "rows": rows, "row_count": total, "truncated": total > limit}
        finally:
            workbook.close()

    def query_trades(self, run: str, sql: str) -> dict[str, Any]:
        path = self.resolve_run(run) / "trade_list.csv"
        if not path.is_file():
            raise ValueError(f"trade_list.csv does not exist for run {run}")
        if ";" in sql:
            raise ValueError("Semicolons and multiple SQL statements are not allowed")
        if not ALLOWED_SQL.match(sql) or FORBIDDEN_SQL.search(sql) or EXTERNAL_SQL.search(sql):
            raise ValueError("Only read-only SELECT, WITH, DESCRIBE, and SHOW queries are allowed")
        with duckdb.connect(":memory:") as connection:
            connection.register("trades", connection.read_csv(str(path), header=True, auto_detect=True))
            cursor = connection.execute(sql)
            columns = [item[0] for item in (cursor.description or [])]
            rows = cursor.fetchmany(5001)
        truncated = len(rows) > 5000
        rows = rows[:5000]
        return {"columns": columns, "rows": [[_json_value(v) for v in row] for row in rows], "row_count": len(rows), "truncated": truncated}

    def compare_runs(self, runs: list[str]) -> list[dict[str, Any]]:
        if not 2 <= len(runs) <= 10 or len(set(runs)) != len(runs):
            raise ValueError("Provide 2-10 distinct run folder names")
        result = []
        aliases = {
            "symbol": ("symbol", "ticker"), "timeframe": ("timeframe", "strategy_timeframe", "strategy_timeframe_minutes"),
            "atr_period": ("atr_period",), "atr_multiplier": ("atr_multiplier",), "total_trades": ("total_trades", "trade_count", "trades"),
            "wins": ("wins", "winning_trades"), "losses": ("losses", "losing_trades"), "win_rate": ("win_rate", "win_rate_percentage"),
            "ending_equity": ("ending_equity", "final_equity"), "total_return_percentage": ("total_return_percentage", "total_return_pct", "return_pct"),
            "profit_factor": ("profit_factor",), "max_drawdown": ("max_drawdown", "max_drawdown_percentage"), "net_profit": ("net_profit", "total_profit"),
        }
        for name in runs:
            folder = self.resolve_run(name)
            summary = self._load_json(folder / "summary.json") if (folder / "summary.json").is_file() else {}
            config = self._load_json(folder / "config.json") if (folder / "config.json").is_file() else {}
            row = {"run": name}
            row.update({field: self._pick([summary, config], *keys) for field, keys in aliases.items()})
            if row["total_trades"] is None and (folder / "trade_list.csv").is_file():
                with (folder / "trade_list.csv").open("r", encoding="utf-8-sig", newline="") as handle:
                    row["total_trades"] = max(sum(1 for _ in handle) - 1, 0)
            result.append(row)
        return result


def resolve_output_root() -> Path:
    configured = os.environ.get("CRYPTO_STRATEGY_LAB_OUTPUT_DIR")
    candidate = Path(configured).expanduser() if configured else Path(__file__).resolve().parents[1] / "output"
    if not candidate.is_dir():
        source = "CRYPTO_STRATEGY_LAB_OUTPUT_DIR" if configured else "the project's default output directory"
        raise RuntimeError(f"Could not resolve {source}: {candidate}. Create it or set CRYPTO_STRATEGY_LAB_OUTPUT_DIR.")
    return candidate.resolve(strict=True)


def create_server(reports: BacktestReports, host: str, port: int):
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("Crypto Strategy Lab Reports", host=host, port=port)

    @server.tool()
    def list_runs(limit: int = 50) -> list[dict[str, Any]]:
        LOGGER.info("MCP tool called: list_runs")
        return reports.list_runs(limit)

    @server.tool()
    def latest_run() -> dict[str, Any]:
        LOGGER.info("MCP tool called: latest_run")
        return reports.latest_run()

    @server.tool()
    def list_run_files(run: str) -> list[dict[str, Any]]:
        LOGGER.info("MCP tool called: list_run_files run=%s", run)
        return reports.list_run_files(run)

    @server.tool()
    def read_report(run: str, filename: str, sheet: str | None = None, limit: int = 200) -> dict[str, Any]:
        LOGGER.info("MCP tool called: read_report run=%s filename=%s", run, filename)
        return reports.read_report(run, filename, sheet, limit)

    @server.tool()
    def query_trades(run: str, sql: str) -> dict[str, Any]:
        LOGGER.info("MCP tool called: query_trades run=%s", run)
        return reports.query_trades(run, sql)

    @server.tool()
    def compare_runs(runs: list[str]) -> list[dict[str, Any]]:
        LOGGER.info("MCP tool called: compare_runs count=%d", len(runs))
        return reports.compare_runs(runs)
    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = resolve_output_root()
    host = "127.0.0.1"
    try:
        port = int(os.environ.get("CRYPTO_STRATEGY_LAB_MCP_PORT", "8765"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError as exc:
        raise SystemExit("CRYPTO_STRATEGY_LAB_MCP_PORT must be an integer from 1 to 65535") from exc
    LOGGER.info("MCP server starting")
    LOGGER.info("Allowed output root: %s", root)
    LOGGER.info("Host: %s", host)
    LOGGER.info("Port: %s", port)
    LOGGER.info("Available tools: list_runs, latest_run, list_run_files, read_report, query_trades, compare_runs")
    create_server(BacktestReports(root), host, port).run(transport="streamable-http")


if __name__ == "__main__":
    main()
