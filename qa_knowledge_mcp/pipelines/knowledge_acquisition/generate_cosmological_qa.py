from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

try:
    from .paths import COSMOLOGICAL_CORE_ROOT, COSMOLOGICAL_QA_ROOT, project_path
except ImportError:
    from paths import COSMOLOGICAL_CORE_ROOT, COSMOLOGICAL_QA_ROOT, project_path

DEFAULT_SYSTEM_PROMPT = """你是宇宙学数值模拟领域的科研知识抽取专家。只依据输入论文全文生成中文问答知识，不得编造。

输出严格 JSON 对象：
{"qa_pairs":[{"question":"...","answer":"...","source_paragraph":"...","source_section":"..."}]}

要求：
1. 每篇生成 15-25 组高信息量问答；短文至少 12 组。
2. 覆盖论文定位、核心问题、模拟项目/代码、数值方法、初始条件、物理模型、数据规模、箱体与分辨率、参数范围、红移范围、精度、关键定量结果、公开数据、应用价值、局限和适用边界。
3. 问题必须可独立检索，尽量在问题中写出论文涉及的项目名、代码名、方法名或物理量。
4. 答案应自包含，优先保留原文的数值、单位、比较对象和限定条件。
5. 不输出泛泛的“本文做了什么”式重复问答；不同问答覆盖不同知识点。
6. 原文没有说明的内容不要补充。不要输出 Markdown 代码围栏或 JSON 之外的文本。
7. source_paragraph 必须是输入原文中的连续段落；无法可靠定位时填空字符串，不得改写或编造原文。"""


def extract_json(content: str) -> dict[str, object]:
    content = content.strip()
    if content.startswith('```'):
        content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content, flags=re.S)
    try:
        return json.loads(content, strict=False)
    except json.JSONDecodeError:
        repaired = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', content)
        try:
            return json.loads(repaired, strict=False)
        except json.JSONDecodeError:
            pass
        match = re.search(r'\{.*\}', content, re.S)
        if not match:
            raise
        candidate = match.group(0)
        candidate = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', candidate)
        return json.loads(candidate, strict=False)


def call_api(text: str, api_url: str, api_key: str, model: str, max_tokens: int, system_prompt: str, min_pairs: int) -> list[dict[str, str]]:
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': text},
        ],
        'max_tokens': max_tokens,
    }
    response = requests.post(
        api_url,
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json=payload,
        timeout=1800,
    )
    response.raise_for_status()
    data = response.json()
    content = data['choices'][0]['message']['content']
    result = extract_json(content)
    pairs = result.get('qa_pairs') or []
    normalized = []
    for pair in pairs:
        question = str(pair.get('question') or '').strip()
        answer = str(pair.get('answer') or '').strip()
        if question and answer:
            normalized.append({
                'question': question,
                'answer': answer,
                'source_paragraph': str(pair.get('source_paragraph') or '').strip(),
                'source_section': str(pair.get('source_section') or '').strip(),
                'source_page_start': pair.get('source_page_start'),
                'source_page_end': pair.get('source_page_end'),
            })
    if len(normalized) < min_pairs:
        raise RuntimeError(f'too few QA pairs: {len(normalized)}')
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, default=COSMOLOGICAL_CORE_ROOT / 'core_papers.json')
    parser.add_argument('--output', type=Path, default=COSMOLOGICAL_QA_ROOT / 'generate_paper.jsonl')
    parser.add_argument('--failures', type=Path, default=COSMOLOGICAL_QA_ROOT / 'failures.json')
    parser.add_argument('--api-url', default=os.environ.get("API_URL"))
    parser.add_argument('--api-key', default=os.environ.get('API_KEY') or os.environ.get('AIGW_API_KEY'))
    parser.add_argument('--model', default=os.environ.get("MODEL"))
    parser.add_argument('--workers', type=int, default=5)
    parser.add_argument('--max-tokens', type=int, default=10000)
    parser.add_argument('--retries', type=int, default=3)
    parser.add_argument('--system-prompt-file', type=Path)
    parser.add_argument('--min-pairs', type=int, default=10)
    args = parser.parse_args()
    if not args.api_url or not args.model:
        parser.error("set API_URL and MODEL or provide --api-url and --model")
    if not args.api_key:
        raise SystemExit('API_KEY or AIGW_API_KEY is required')

    args.manifest = project_path(args.manifest)
    args.output = project_path(args.output)
    args.failures = project_path(args.failures)
    system_prompt = DEFAULT_SYSTEM_PROMPT
    if args.system_prompt_file:
        prompt_path = project_path(args.system_prompt_file)
        system_prompt = prompt_path.read_text(encoding='utf-8')
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, object]] = {}
    if args.output.exists():
        for line in args.output.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            existing[str(row['hash'])] = row

    tasks = []
    for item in manifest:
        source = project_path(item['source'])
        text = source.read_text(encoding='utf-8', errors='ignore')
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if digest in existing and (existing[digest].get('result') or {}).get('qa_pairs'):
            continue
        tasks.append((item, text, digest))

    lock = threading.Lock()
    new_rows: dict[str, dict[str, object]] = {}
    failures = []

    def process(task: tuple[dict[str, object], str, str]) -> dict[str, object]:
        item, text, digest = task
        last_error = None
        for attempt in range(args.retries):
            try:
                pairs = call_api(text, args.api_url, args.api_key, args.model, args.max_tokens, system_prompt, args.min_pairs)
                return {
                    'hash': digest,
                    'result': {'qa_pairs': pairs},
                    'metadata': {
                        'rank': item['rank'], 'key': item['key'], 'title': item['title'],
                        'category': item['category'], 'source': item['source'],
                    },
                }
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(10 * (attempt + 1))
        raise RuntimeError(str(last_error))

    def flush() -> None:
        rows = {**existing, **new_rows}
        ordered = sorted(rows.values(), key=lambda row: int((row.get('metadata') or {}).get('rank', 999999)))
        temp = args.output.with_suffix('.jsonl.tmp')
        with temp.open('w', encoding='utf-8') as handle:
            for row in ordered:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        temp.replace(args.output)

    print(f'total={len(manifest)} cached={len(existing)} pending={len(tasks)}', flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_map = {executor.submit(process, task): task for task in tasks}
        for future in as_completed(future_map):
            item, _, digest = future_map[future]
            try:
                row = future.result()
                with lock:
                    new_rows[digest] = row
                    flush()
                print(f"OK {item['rank']:03d} {item['key']} pairs={len(row['result']['qa_pairs'])}", flush=True)
            except Exception as exc:  # noqa: BLE001
                failures.append({'rank': item['rank'], 'key': item['key'], 'title': item['title'], 'error': str(exc)})
                print(f"FAIL {item['rank']:03d} {item['key']}: {exc}", flush=True)
    args.failures.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'done success={len(existing)+len(new_rows)} failed={len(failures)}', flush=True)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
