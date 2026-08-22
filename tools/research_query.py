"""Run an artifact-only Task-16 descriptive research query."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from crypto_strategy_lab.feature_research import ResearchQueryService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path, help="JSON query specification")
    parser.add_argument("--output", type=Path, help="optional CSV output (JSON is printed otherwise)")
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    with ResearchQueryService(args.run_dir) as service:
        result = service.query(spec)
    if args.output:
        result.to_csv(args.output, index=False)
    else:
        print(result.to_json(orient="records", date_format="iso", indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
