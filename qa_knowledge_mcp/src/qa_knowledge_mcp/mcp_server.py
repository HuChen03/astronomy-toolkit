from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .knowledge_catalog import KnowledgeBaseCatalog
from .paths import COSMOLOGICAL_DATA_ROOT, INDEX_ROOT, KNOWLEDGE_OVERLAY_DB, PROJECT_ROOT
from .versioned_index import active_index


def create_server(
    source_path: Path,
    index_path: Path | None = None,
    *,
    catalog_path: Path = PROJECT_ROOT / "config/knowledge_bases",
    overlay_path: Path = KNOWLEDGE_OVERLAY_DB,
    host: str = "0.0.0.0",
    port: int = 8001,
) -> FastMCP:
    catalog = KnowledgeBaseCatalog(catalog_path, main_source=source_path, main_index=index_path, overlay_path=overlay_path)
    server = FastMCP(
        "astronomy-knowledge",
        instructions=(
            "This is an astronomy knowledge-base search server. It exposes only two read-only tools. "
            "list_knowledge_bases lists astronomy QA databases. search_knowledge searches the main "
            "astronomy database by default; when knowledge_base_ids are provided, the main database "
            "and requested small-direction databases are searched together. Results are retrieved QA "
            "pairs with linked source paragraphs."
        ),
        host=host,
        port=port,
        streamable_http_path="/mcp",
        json_response=True,
        # Stateful sessions: each client connection gets its own Mcp-Session-Id,
        # so concurrent clients (and their standalone SSE GET streams) do not
        # conflict with each other.
        stateless_http=False,
    )

    @server.tool(structured_output=True)
    def list_knowledge_bases() -> dict[str, Any]:
        """List active astronomy QA databases and their paper/QA counts."""
        databases = catalog.list()
        return {"knowledge_bases": databases, "count": len(databases)}

    @server.tool(structured_output=True)
    def search_knowledge(
        query: str,
        knowledge_base_ids: list[str] | None = None,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> dict[str, Any]:
        """Search astronomy QA pairs and linked source paragraphs. Without knowledge_base_ids, search only main."""
        return catalog.search(query, knowledge_base_ids=knowledge_base_ids, top_k=top_k, min_score=min_score)

    return server

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the QA knowledge MCP server.")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(
            os.environ.get(
                "QA_SOURCE",
                COSMOLOGICAL_DATA_ROOT / "generate_paper.jsonl",
            )
        ),
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=(Path(os.environ["QA_INDEX"]) if os.environ.get("QA_INDEX") else (active_index(INDEX_ROOT) or COSMOLOGICAL_DATA_ROOT / "index")),
    )
    parser.add_argument("--knowledge-base-config", type=Path, default=Path(os.environ.get("QA_KNOWLEDGE_BASE_CONFIG", PROJECT_ROOT / "config/knowledge_bases")))
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default=os.environ.get("QA_MCP_TRANSPORT", "stdio"))
    parser.add_argument("--host", default=os.environ.get("QA_MCP_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("QA_MCP_PORT", "8001")))
    args = parser.parse_args()
    server = create_server(args.source, args.index, catalog_path=args.knowledge_base_config, host=args.host, port=args.port)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
