from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from lab_knowledge_platform.hub_client import LiteratureHubClient, LiteratureHubSettings
from lab_knowledge_platform.paths import PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask the literature hub to backfill Markdown paths.")
    parser.add_argument("markdown_dir", type=Path)
    parser.add_argument("--remote-dir", help="Path as visible to the literature hub shared filesystem")
    parser.add_argument("--base-url", default=os.environ.get("LITERATURE_HUB_BASE_URL", ""))
    parser.add_argument("--write", action="store_true", help="Write paths to the hub; default is dry-run.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--max-files", type=int)
    args = parser.parse_args()
    if not args.base_url.strip():
        parser.error("configure LITERATURE_HUB_BASE_URL or pass --base-url")
    directory = args.markdown_dir if args.markdown_dir.is_absolute() else PROJECT_ROOT / args.markdown_dir
    remote_directory = args.remote_dir or str(directory)
    result = LiteratureHubClient(LiteratureHubSettings(args.base_url.rstrip("/"))).backfill_markdown(
        remote_directory, overwrite=args.overwrite, dry_run=not args.write, max_files=args.max_files,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
