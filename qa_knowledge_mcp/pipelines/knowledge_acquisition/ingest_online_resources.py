from __future__ import annotations

import argparse
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

from .paths import project_path


RESOURCES = [
    {
        "key": "desi-data-release-docs",
        "title": "DESI Data Release Documentation",
        "year": 2026,
        "category": "DESI官方数据发布文档",
        "url": "https://data.desi.lbl.gov/doc/",
    },
    {
        "key": "desi-data-model",
        "title": "DESI Data Model Documentation",
        "year": 2026,
        "category": "DESI官方数据模型",
        "url": "https://desidatamodel.readthedocs.io/en/latest/index.html",
    },
    {
        "key": "desihub-desihub",
        "title": "DESI Hub GitHub Organization",
        "year": 2026,
        "category": "DESI官方代码资源",
        "url": "https://github.com/desihub",
    },
    {
        "key": "desihub-desispec",
        "title": "desihub/desispec: DESI Spectroscopic Pipeline",
        "year": 2026,
        "category": "DESI官方代码资源",
        "url": "https://github.com/desihub/desispec",
    },
]


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg", "canvas"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg", "canvas"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            value = html.unescape(data).strip()
            if value:
                self.parts.append(value)


def normalize_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "multitarget-fiber-spectroscopy-kb/1.0"})
    with urlopen(request, timeout=120) as response:
        content_type = response.headers.get_content_type()
        payload = response.read()
    if content_type == "text/plain" or url.endswith(".txt"):
        return payload.decode("utf-8", errors="replace")
    parser = VisibleTextParser()
    parser.feed(payload.decode("utf-8", errors="replace"))
    return "\n\n".join(normalize_text(part) for part in parser.parts if len(normalize_text(part)) > 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch official online resources for the multi-target fiber spectroscopy KB.")
    parser.add_argument("--root", type=Path, default=Path("data/knowledge_bases/multitarget_fiber_spectroscopy"))
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args()
    root = project_path(args.root)
    output_root = root / "resources"
    output_root.mkdir(parents=True, exist_ok=True)
    records = []
    for rank, resource in enumerate(RESOURCES, start=1):
        output = output_root / f"{resource['key']}.md"
        status = "ready" if output.exists() else "missing"
        error = None
        if not args.skip_fetch:
            try:
                text = fetch_text(resource["url"])
                if len(text) < 200:
                    raise RuntimeError(f"too little visible text: {len(text)} characters")
                output.write_text(f"# {resource['title']}\n\nSource URL: {resource['url']}\n\n{text}\n", encoding="utf-8")
                status = "ready"
            except Exception as exc:  # noqa: BLE001
                status = "fetch_failed"
                error = f"{type(exc).__name__}: {exc}"
        records.append({
            "rank": rank,
            "key": resource["key"],
            "title": resource["title"],
            "year": resource["year"],
            "category": resource["category"],
            "source": str(output.relative_to(root.parent.parent.parent)),
            "source_url": resource["url"],
            "status": status,
            **({"error": error} if error else {}),
        })
    (root / "resources.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"resources": len(records), "ready": sum(row["status"] == "ready" for row in records), "records": records}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
