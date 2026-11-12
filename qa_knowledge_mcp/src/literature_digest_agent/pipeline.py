from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .classifier import load_taxonomy
from .config import RunSettings
from .email_renderer import render_email
from .hub_client import LiteratureHubClient
from .keywords import load_keyword_categories
from .mailer import send_html_email
from .service import process_digest_payload


def run(settings: RunSettings) -> dict[str, Any]:
    categories = load_keyword_categories(settings.keywords_path)
    taxonomy = load_taxonomy(settings.taxonomy_path, categories)
    if settings.input_digest_path:
        hub_payload = json.loads(settings.input_digest_path.read_text(encoding="utf8"))
    else:
        hub_payload = LiteratureHubClient(settings.hub).fetch_daily_digest(
            digest_date=settings.digest_date,
            discipline=settings.discipline,
            limit=settings.limit,
        )
    digest = process_digest_payload(
        hub_payload,
        categories,
        taxonomy=taxonomy,
        enable_llm_classification=settings.enable_llm_classification,
        max_workers=settings.max_workers,
    )

    if settings.email:
        subject, html = render_email(digest, settings.discipline)
        digest["email_delivery"] = {
            "requested": True,
            "sent": send_html_email(settings.smtp, subject, html),
            "recipients": list(settings.smtp.recipients),
        }
    else:
        digest["email_delivery"] = {"requested": False, "sent": False, "recipients": []}

    if settings.output_path:
        write_json(settings.output_path, digest)

    return digest


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
