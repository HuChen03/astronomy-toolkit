from __future__ import annotations

import argparse
import json

from .config import CatalogSettings
from .daily_catalog import refresh_daily_catalog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh the local daily literature catalog.")
    parser.add_argument(
        "--date",
        help="Window end date in YYYY-MM-DD; defaults to the latest 08:00 cutoff",
    )
    parser.add_argument("--force", action="store_true", help="Publish a new snapshot even if one already exists")
    parser.add_argument(
        "--skip-automation-check",
        action="store_true",
        help="Refresh even when upstream automation jobs are still running",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = refresh_daily_catalog(
        CatalogSettings.from_env(),
        business_date=args.date,
        force=args.force,
        skip_automation_check=args.skip_automation_check,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
