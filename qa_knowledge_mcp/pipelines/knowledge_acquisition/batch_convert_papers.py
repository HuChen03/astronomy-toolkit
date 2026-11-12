from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import requests


DEFAULT_SYSTEM_PROMPT = """You are a helpful assistant.
请将输入的科研论文 Markdown 内容转化为中文结构化结果。
要求：
1. 保留论文核心信息，不要编造。
2. 输出为 Markdown。
3. 结果按以下结构组织：
   - 标题：论文题目
   - 一句话概述
   - 研究背景
   - 核心方法
   - 关键结果
   - 结论与意义
4. 如果文中包含公式、缩写、英文术语、专有名词，请保留原文或中英并列。
5. 如果原文很长，请尽量压缩，但不要遗漏关键结论和方法。
"""


def iter_markdown_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.md")):
        if path.is_file():
            yield path


def build_output_path(source: Path, input_root: Path, output_root: Path) -> Path:
    relative = source.relative_to(input_root)
    return output_root / relative.with_suffix(".converted.md")


def call_api(api_url: str, api_key: str, model: str, content: str, temperature: float | None) -> str:
    payload: dict[str, object] = {
        "model": model,
        "chat_template_kwargs": {"enable_thinking": True},
        "messages": [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    }
    if temperature is not None:
        payload.update({"temperature": temperature, "top_p": 0.95, "top_k": 40})

    response = requests.post(
        api_url,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        json=payload,
        timeout=1800,
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"API response missing choices: {data}")
    message = choices[0].get("message", {})
    result = message.get("content")
    if not isinstance(result, str):
        raise RuntimeError(f"API response missing content: {data}")
    return result


def process_file(source: Path, input_root: Path, output_root: Path, api_url: str, api_key: str, model: str, temperature: float | None) -> tuple[Path, Path, str | None]:
    output_path = build_output_path(source, input_root, output_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and output_path.stat().st_size > 0:
        return source, output_path, None

    text = source.read_text(encoding="utf-8", errors="ignore")
    converted = call_api(api_url, api_key, model, text, temperature)
    output_path.write_text(converted, encoding="utf-8")
    return source, output_path, converted


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch convert Markdown papers with the provided API.")
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--api-url", default=os.environ.get("API_URL"))
    parser.add_argument("--api-key", default=os.environ.get("API_KEY"))
    parser.add_argument("--model", default=os.environ.get("MODEL"))
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if not args.api_url or not args.model:
        parser.error("set API_URL and MODEL or provide --api-url and --model")
    if not args.api_key:
        raise SystemExit("API key is required via --api-key or API_KEY env var")

    sources = list(iter_markdown_files(args.input_root))
    if args.limit is not None:
        sources = sources[: args.limit]

    args.output_root.mkdir(parents=True, exist_ok=True)
    manifest = []
    failures = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_file,
                source,
                args.input_root,
                args.output_root,
                args.api_url,
                args.api_key,
                args.model,
                args.temperature,
            ): source
            for source in sources
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                src, dst, _ = future.result()
                manifest.append({"source": str(src), "output": str(dst)})
                print(f"OK {src} -> {dst}")
            except Exception as exc:  # noqa: BLE001
                failures.append({"source": str(source), "error": str(exc)})
                print(f"FAIL {source}: {exc}")

    (args.output_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_root / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"done: {len(manifest)} ok, {len(failures)} failed")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
