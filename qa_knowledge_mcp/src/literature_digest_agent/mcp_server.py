from __future__ import annotations

import argparse
import os
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .config import CatalogSettings
from .daily_catalog import previous_business_date, refresh_daily_catalog
from .repository import DigestRepository


def create_server(
    settings: CatalogSettings | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8002,
) -> FastMCP:
    catalog_settings = settings or CatalogSettings.from_env()
    repository = DigestRepository(catalog_settings.database_path)
    server = FastMCP(
        "daily-literature",
        instructions=(
            "Query the prepared near-24-hour literature catalog by predefined categories. "
            "Use list_categories before get_daily_digest when category IDs are unknown."
        ),
        host=host,
        port=port,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
    )

    @server.tool(structured_output=True)
    def list_tags(date: str | None = None) -> dict[str, Any]:
        """List tags available in the latest or requested daily snapshot."""
        return repository.list_tags(
            resolve_query_date(date, catalog_settings.timezone),
            catalog_settings.discipline,
        )

    @server.tool(structured_output=True)
    def list_categories(date: str | None = None) -> dict[str, Any]:
        """List model-selected categories available in a requested near-24-hour snapshot."""
        result = repository.list_tags(
            resolve_query_date(date, catalog_settings.timezone),
            catalog_settings.discipline,
        )
        return {
            **result,
            "categories": result.get("tags") or [],
        }

    @server.tool(structured_output=True)
    def get_daily_papers(
        tags: list[str],
        date: str | None = None,
        match_mode: Literal["any", "all"] = "any",
        limit: int = 20,
        offset: int = 0,
        sort: Literal["relevance", "published_desc", "upstream_score"] = "relevance",
    ) -> dict[str, Any]:
        """Return paper briefs matching one or more configured tag IDs."""
        return repository.query_papers(
            tags,
            business_date=resolve_query_date(date, catalog_settings.timezone),
            discipline=catalog_settings.discipline,
            match_mode=match_mode,
            limit=limit,
            offset=offset,
            sort=sort,
        )

    @server.tool(structured_output=True)
    def get_daily_digest(
        date: str | None = None,
        category_ids: list[str] | None = None,
        match_mode: Literal["any", "all"] = "any",
        limit: int = 20,
        offset: int = 0,
        sort: Literal["relevance", "published_desc", "upstream_score"] = "relevance",
    ) -> dict[str, Any]:
        """Return paper categories and hub-provided briefs for a near-24-hour snapshot."""
        query_date = resolve_query_date(date, catalog_settings.timezone)
        selected_categories = category_ids
        if not selected_categories:
            selected_categories = [
                row["id"]
                for row in repository.list_tags(query_date, catalog_settings.discipline).get("tags") or []
            ]
        result = repository.query_papers(
            selected_categories,
            business_date=query_date,
            discipline=catalog_settings.discipline,
            match_mode=match_mode,
            limit=limit,
            offset=offset,
            sort=sort,
        )
        return {
            **result,
            "requested_categories": selected_categories,
        }

    @server.tool(structured_output=True)
    def get_daily_summary(
        date: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return the global daily summary or summaries for selected tags."""
        return repository.get_daily_summary(
            business_date=resolve_query_date(date, catalog_settings.timezone),
            discipline=catalog_settings.discipline,
            tags=tags,
        )

    @server.tool(structured_output=True)
    def get_paper(paper_id: str, date: str | None = None) -> dict[str, Any]:
        """Return the stored enriched record for one paper."""
        paper = repository.get_paper(
            paper_id,
            business_date=resolve_query_date(date, catalog_settings.timezone),
            discipline=catalog_settings.discipline,
        )
        return {"found": paper is not None, "paper": sanitize_paper(paper) if paper else None}

    @server.tool(structured_output=True)
    def get_sync_status(date: str | None = None) -> dict[str, Any]:
        """Return the latest catalog refresh and upstream automation status."""
        return repository.get_sync_status(
            resolve_query_date(date, catalog_settings.timezone),
            catalog_settings.discipline,
        )

    @server.tool(structured_output=True)
    def refresh_daily_catalog_tool(
        date: str | None = None,
        force: bool = False,
        admin_token: str = "",
    ) -> dict[str, Any]:
        """Refresh a daily snapshot. Requires the server-side administrator token."""
        expected_token = os.environ.get("LDA_MCP_ADMIN_TOKEN", "")
        if not expected_token:
            raise PermissionError("manual refresh is disabled")
        if admin_token != expected_token:
            raise PermissionError("invalid administrator token")
        return refresh_daily_catalog(
            catalog_settings,
            business_date=date,
            force=force,
        )

    @server.resource(
        "literature-digest://schema/query",
        name="Daily literature query schema",
        mime_type="application/json",
    )
    def query_schema() -> dict[str, Any]:
        return {
            "category_ids": "Optional IDs returned by list_categories; omitted means all categories",
            "match_mode": ["any", "all"],
            "date": "Optional YYYY-MM-DD; latest published snapshot when omitted",
            "limit": "1-100",
            "offset": "Non-negative result offset",
            "sort": ["relevance", "published_desc", "upstream_score"],
        }

    return server


def sanitize_paper(paper: dict[str, Any]) -> dict[str, Any]:
    output = dict(paper)
    output.pop("pdf_path", None)
    output.pop("markdown_path", None)
    return output


def resolve_query_date(value: str | None, timezone_name: str) -> str:
    return value or previous_business_date(timezone_name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the literature digest MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.environ.get("LDA_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.environ.get("LDA_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LDA_MCP_PORT", "8002")))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    server = create_server(host=args.host, port=args.port)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
