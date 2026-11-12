from __future__ import annotations

import html
from datetime import datetime
from typing import Any


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def render_email(digest: dict[str, Any], discipline: str) -> tuple[str, str]:
    items = digest.get("items") or []
    current_date = digest.get("date") or datetime.now().strftime("%Y-%m-%d")
    subject = f"Literature Digest {current_date} [{discipline}, {len(items)} papers]"
    content = "\n".join(render_item(index, item) for index, item in enumerate(items, start=1))
    if not content:
        content = '<section class="paper"><h3>No papers</h3><p>No daily digest items were returned.</p></section>'

    summary = digest.get("summary") or ""
    html_content = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: Arial, sans-serif; color: #222; line-height: 1.55; }}
    .header {{ padding: 18px; background: #f5f7fb; border: 1px solid #e2e6ef; }}
    .header h2 {{ margin: 0 0 8px 0; }}
    .summary {{ margin-top: 8px; color: #444; }}
    .paper {{ margin: 22px 0; padding: 16px; border-left: 4px solid #2563eb; background: #fafafa; }}
    .paper h3 {{ margin: 0 0 8px 0; font-size: 18px; }}
    .meta, .small {{ color: #666; font-size: 13px; }}
    .badge {{ display: inline-block; padding: 2px 7px; margin: 2px 4px 2px 0; border-radius: 4px; background: #e8f0fe; color: #174ea6; font-size: 12px; }}
    .priority {{ color: #0f766e; font-weight: bold; }}
    .review {{ color: #9a3412; }}
    a {{ color: #2563eb; }}
  </style>
</head>
<body>
  <div class="header">
    <h2>Literature Digest {esc(current_date)}</h2>
    <div>{esc(discipline)} · {len(items)} papers</div>
    <div class="summary">{esc(summary)}</div>
  </div>
  {content}
</body>
</html>"""
    return subject, html_content


def render_item(index: int, item: dict[str, Any]) -> str:
    classification = item.get("classification") or {}
    primary = classification.get("primary_category") or {}
    keyword_categories = item.get("keyword_categories") or []
    badges = "".join(
        f'<span class="badge">{esc(row.get("category"))}: {esc(", ".join(row.get("matched_terms") or []))}</span>'
        for row in keyword_categories
    )
    generated = ", ".join(classification.get("generated_keywords") or item.get("extracted_keywords") or [])
    authors = ", ".join(item.get("authors") or [])
    review = ""
    if classification.get("needs_human_review"):
        review = f'<div class="review small">Review: {esc(", ".join(classification.get("review_reasons") or []))}</div>'
    links = render_links(item)
    abstract = item.get("summary") or item.get("abstract") or ""
    return f"""
<section class="paper">
  <h3>[{index}] {esc(item.get("title"))}</h3>
  <div class="meta">{esc(item.get("published_at") or "")} · {esc(item.get("venue") or "")} · {esc(authors)}</div>
  <div class="priority">Priority score: {esc(item.get("priority_score", ""))} · Keyword score: {esc(item.get("keyword_score", ""))}</div>
  <div>{badges}</div>
  <p>{esc(abstract)}</p>
  <div><strong>Category:</strong> {esc(primary.get("name") or "Unmatched")} · <strong>Classifier:</strong> {esc(classification.get("mode", ""))}</div>
  <div><strong>Keywords:</strong> {esc(generated)}</div>
  {review}
  {links}
</section>"""


def render_links(item: dict[str, Any]) -> str:
    links = []
    if item.get("doi"):
        links.append(f'<a href="https://doi.org/{esc(item["doi"])}">DOI</a>')
    if item.get("arxiv_id"):
        links.append(f'<a href="https://arxiv.org/abs/{esc(item["arxiv_id"])}">arXiv</a>')
    if item.get("pdf_path"):
        links.append(f'<span class="small">PDF: {esc(item["pdf_path"])}</span>')
    if item.get("markdown_path"):
        links.append(f'<span class="small">Markdown: {esc(item["markdown_path"])}</span>')
    return '<div class="small">' + " · ".join(links) + "</div>" if links else ""
