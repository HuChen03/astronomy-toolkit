from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

try:
    from .paths import project_path
except ImportError:
    from paths import project_path


SYSTEM_PROMPT = """你是一名严谨的科研论文知识抽取专家。请只依据输入论文全文，输出中文 Markdown。

必须尽可能完整地抽取可复用知识，不要编造，不要省略关键限定条件。结构如下：
1. 论文元数据：标题、作者、年份、期刊、DOI/arXiv（文中存在时）
2. 一句话核心结论
3. 研究问题与背景
4. 核心概念与术语
5. 方法与技术路线：模型、算法、方程、假设、参数、数据、实验或模拟设置
6. 关键结果：尽量保留定量结果、适用尺度、红移、精度、比较基线和不确定性
7. 结论、意义与可复用启示
8. 局限性与适用边界
9. 重要公式：用 LaTeX 抄录或忠实转述，并解释变量和用途
10. 知识问答：生成 12–25 组高信息量问答，覆盖方法、结果、原因、比较、限制和应用
11. 检索关键词：中英文并列

若原文某项未提供，明确写“原文未说明”。不要根据常识补充原文之外的事实。"""


def parse_entries(library_path: Path) -> list[dict[str, object]]:
    text = library_path.read_text(encoding="utf-8")
    matches = list(re.finditer(r"^### (\d+)\. (.+)$", text, re.MULTILINE))
    entries: list[dict[str, object]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end() : end]
        doi_match = re.search(r"https://doi\.org/([^\s]+)", block)
        arxiv_match = re.search(r"https://arxiv\.org/abs/([^\s]+)", block)
        doi = doi_match.group(1).rstrip("。；") if doi_match else None
        arxiv = arxiv_match.group(1).rstrip("。；") if arxiv_match else None
        entries.append(
            {
                "number": int(match.group(1)),
                "title": match.group(2).strip(),
                "doi": doi,
                "arxiv": arxiv,
            }
        )
    return entries


def source_key(entry: dict[str, object]) -> str | None:
    doi = entry.get("doi")
    if isinstance(doi, str):
        return doi.lower().replace("/", "_")
    arxiv = entry.get("arxiv")
    if isinstance(arxiv, str):
        return f"10.48550_arxiv.{arxiv.lower().replace('/', '_')}"
    return None


def normalized_title(value: str) -> set[str]:
    value = re.sub(r"\\[A-Za-z]+|[^a-z0-9]+", " ", value.lower())
    return {token for token in value.split() if len(token) > 1}


def title_matches(entry: dict[str, object], path: Path) -> bool:
    head = path.read_text(encoding="utf-8", errors="ignore")[:16000]
    headings = re.findall(r"^#\s+(.+)$", head, re.MULTILINE)
    if not headings:
        return False
    target_tokens = normalized_title(str(entry["title"]))
    source_tokens = normalized_title(headings[0])
    if not target_tokens or not source_tokens:
        return False
    return len(target_tokens & source_tokens) / len(target_tokens) >= 0.65


def locate_source(entry: dict[str, object], source_root: Path) -> tuple[Path | None, str]:
    key = source_key(entry)
    if key:
        direct = source_root / key / f"{key}.md"
        if direct.exists():
            if title_matches(entry, direct):
                return direct, "matched"
            return None, "source_title_mismatch"

    exact_hits: list[Path] = []
    for path in source_root.glob("*/*.md"):
        if title_matches(entry, path):
            exact_hits.append(path)
    if len(exact_hits) == 1:
        return exact_hits[0], "matched"
    return None, "source_missing"


def call_api(api_url: str, api_key: str, model: str, content: str, max_output_tokens: int) -> str:
    is_responses_api = api_url.rstrip("/").endswith("/responses")
    if is_responses_api:
        payload: dict[str, object] = {
            "model": model,
            "instructions": SYSTEM_PROMPT,
            "input": content,
            "max_output_tokens": max_output_tokens,
        }
    else:
        payload = {
            "model": model,
            "chat_template_kwargs": {"enable_thinking": True},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "max_tokens": max_output_tokens,
        }
    response = requests.post(
        api_url,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=1800,
    )
    response.raise_for_status()
    data = response.json()
    if is_responses_api:
        if isinstance(data.get("output_text"), str):
            return data["output_text"]
        parts = []
        for output in data.get("output") or []:
            for item in output.get("content") or []:
                if item.get("type") == "output_text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
        if parts:
            return "\n".join(parts)
        raise RuntimeError(f"API response missing output text: {data}")
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0].get("message", {}).get("content"), str):
        raise RuntimeError(f"API response missing content: {data}")
    return choices[0]["message"]["content"]


def extract_one(entry: dict[str, object], source: Path, output_root: Path, api_url: str, api_key: str, model: str, max_output_tokens: int) -> dict[str, object]:
    key = source.parent.name
    output = output_root / "papers" / f"{int(entry['number']):03d}_{key}.knowledge.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists() or output.stat().st_size == 0:
        paper = source.read_text(encoding="utf-8", errors="ignore")
        result = call_api(api_url, api_key, model, paper, max_output_tokens)
        output.write_text(result.strip() + "\n", encoding="utf-8")
    return {**entry, "status": "extracted", "source": str(source), "output": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, default=Path("data/knowledge_acquisition/raw/1.md"))
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("data/knowledge_acquisition/paper_library_1_knowledge"))
    parser.add_argument("--api-url", default=os.environ.get("API_URL"))
    parser.add_argument("--api-key", default=os.environ.get("API_KEY") or os.environ.get("AIGW_API_KEY"))
    parser.add_argument("--model", default=os.environ.get("MODEL"))
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--max-output-tokens", type=int, default=20000)
    args = parser.parse_args()
    args.library = project_path(args.library)
    args.source_root = project_path(args.source_root)
    args.output_root = project_path(args.output_root)

    entries = parse_entries(args.library)
    located: list[tuple[dict[str, object], Path]] = []
    manifest: list[dict[str, object]] = []
    for entry in entries:
        source, locate_status = locate_source(entry, args.source_root)
        if source:
            located.append((entry, source))
        else:
            manifest.append({**entry, "status": locate_status, "source": None, "output": None})

    if located and (not args.api_url or not args.model):
        parser.error("set API_URL and MODEL or provide --api-url and --model")
    if located and not args.api_key:
        raise SystemExit("API key is required via API_KEY or AIGW_API_KEY")

    failures: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(extract_one, entry, source, args.output_root, args.api_url, args.api_key, args.model, args.max_output_tokens): (entry, source)
            for entry, source in located
        }
        for future in as_completed(futures):
            entry, source = futures[future]
            try:
                record = future.result()
                manifest.append(record)
                print(f"OK {entry['number']} {source.name}", flush=True)
            except Exception as exc:  # noqa: BLE001
                record = {**entry, "status": "failed", "source": str(source), "output": None, "error": str(exc)}
                manifest.append(record)
                failures.append(record)
                print(f"FAIL {entry['number']} {source.name}: {exc}", flush=True)

    manifest.sort(key=lambda item: int(item["number"]))
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    extracted = [item for item in manifest if item["status"] == "extracted"]
    missing = [item for item in manifest if item["status"] in {"source_missing", "source_title_mismatch"}]
    index_lines = ["# 论文库1知识提取索引", "", f"- 可识别条目：{len(entries)}", f"- 成功提取：{len(extracted)}", f"- 指定目录缺失：{len(missing)}", ""]
    for item in extracted:
        relative = Path(str(item["output"])).relative_to(args.output_root)
        index_lines.append(f"- {item['number']}. [{item['title']}]({relative.as_posix()})")
    index_lines.extend(["", "## 未定位全文", ""])
    for item in missing:
        identifier = item.get("doi") or (f"arXiv:{item['arxiv']}" if item.get("arxiv") else "无 DOI/arXiv")
        index_lines.append(f"- {item['number']}. {item['title']}（{identifier}）")
    (args.output_root / "README.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    print(f"done: {len(extracted)} extracted, {len(missing)} source missing, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
