from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from .config import HubSettings, RunSettings
from .pipeline import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch literature hub daily digest, classify papers, and send email.")
    parser.add_argument("--hub-base-url", help="Literature hub API base URL")
    parser.add_argument("--date", help="Digest date in YYYY-MM-DD")
    parser.add_argument("--discipline", help="Digest discipline, e.g. cond-mat")
    parser.add_argument("--limit", type=int, help="Maximum number of digest items")
    parser.add_argument("--keywords", type=Path, help="Keyword category JSON file")
    parser.add_argument("--taxonomy", type=Path, help="Optional custom taxonomy JSON file for LLM classification")
    parser.add_argument("--input-digest", type=Path, help="Read a local digest JSON instead of calling the literature hub")
    parser.add_argument("--output", type=Path, help="Write enriched digest JSON to this path")
    parser.add_argument("--email", action="store_true", help="Send HTML email after classification")
    parser.add_argument("--llm-classification", action="store_true", help="Use literature_classification_agent when OPENAI_API_KEY is set")
    parser.add_argument("--max-workers", type=int, help="LLM classification worker count")
    parser.add_argument("--print-json", action="store_true", help="Print the full enriched digest JSON")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = apply_args(RunSettings.from_env(), args)
    digest = run(settings)
    if args.print_json:
        print(json.dumps(digest, ensure_ascii=False, indent=2))
    else:
        stats = digest.get("keyword_agent") or {}
        print(
            "digest complete: "
            f"{len(digest.get('items') or [])} items, "
            f"{stats.get('matched_items', 0)} keyword matches"
        )


def apply_args(settings: RunSettings, args: argparse.Namespace) -> RunSettings:
    hub = settings.hub
    if args.hub_base_url:
        hub = HubSettings(base_url=args.hub_base_url.rstrip("/"), timeout_seconds=hub.timeout_seconds)
    project_root = Path(__file__).resolve().parents[2]
    keywords_path = args.keywords or settings.keywords_path
    if not keywords_path.exists() and not keywords_path.is_absolute():
        candidate = project_root / keywords_path
        if candidate.exists():
            keywords_path = candidate
    taxonomy_path = args.taxonomy or settings.taxonomy_path
    if taxonomy_path and not taxonomy_path.exists() and not taxonomy_path.is_absolute():
        candidate = project_root / taxonomy_path
        if candidate.exists():
            taxonomy_path = candidate
    input_digest_path = args.input_digest or settings.input_digest_path
    if input_digest_path and not input_digest_path.exists() and not input_digest_path.is_absolute():
        candidate = project_root / input_digest_path
        if candidate.exists():
            input_digest_path = candidate
    return replace(
        settings,
        hub=hub,
        digest_date=args.date or settings.digest_date,
        discipline=args.discipline or settings.discipline,
        limit=args.limit if args.limit is not None else settings.limit,
        keywords_path=keywords_path,
        taxonomy_path=taxonomy_path,
        input_digest_path=input_digest_path,
        output_path=args.output or settings.output_path,
        email=args.email or settings.email,
        enable_llm_classification=args.llm_classification or settings.enable_llm_classification,
        max_workers=args.max_workers or settings.max_workers,
    )


if __name__ == "__main__":
    main()
