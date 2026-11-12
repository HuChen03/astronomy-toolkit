# Lab Knowledge MCP 接口文档

## 1. 服务概览

当前 MCP 只提供知识库能力，不再对外提供日报、Evidence Pack、Topic、Decision 或独立 Evidence 管理工具。

服务默认配置：

```text
服务名称：astronomy-knowledge
传输协议：MCP Streamable HTTP
监听端口：8001
MCP 路径：/mcp
默认地址：http://<服务器IP>:8001/mcp
```

这是天文学/宇宙学知识库搜索服务。知识库的最小检索单元是 QA Pair，并携带其对应的原文段落。服务只返回检索结果，不生成新的最终答案。

每日论文是独立的 `daily-literature` MCP 服务，默认监听 `8002`，文档和启动脚本见 `README.md`；它不属于本服务的工具集合。

## 2. 启动

本仓库包含两个互不注册工具的 MCP 进程：

| 服务 | 端口 | 用途 | 启动脚本 |
|---|---:|---|---|
| `astronomy-knowledge` | `8001` | 天文学/宇宙学 QA 与原文段落检索 | `run_cosmological_mcp.sh` |
| `daily-literature` | `8002` | 每日论文快照、分类和查询 | `run_literature_digest_mcp.sh` |

下文只描述 `astronomy-knowledge` 的接口。

```bash
cd /path/to/astronomy-toolkit/qa_knowledge_mcp
QA_ENABLE_EMBEDDING=false QA_ENABLE_RERANKER=false \
python3 -m qa_knowledge_mcp.mcp_server \
  --transport streamable-http \
  --host 0.0.0.0 \
  --port 8001
```

也可以执行：

```bash
./run_cosmological_mcp.sh
```

知识库配置目录默认为 `config/knowledge_bases`，也可以通过 `QA_KNOWLEDGE_BASE_CONFIG` 或 `--knowledge-base-config` 指定。

## 3. 工具

### 3.1 `list_knowledge_bases`

列出当前配置目录中已启用的知识库。返回结果包括知识库 ID、名称、描述、状态、来源、索引位置以及 QA/论文数量。

调用：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "list_knowledge_bases",
    "arguments": {}
  }
}
```

返回示例：

```json
{
  "knowledge_bases": [
    {
      "id": "main",
      "name": "主知识库",
      "description": "实验室主 QA 知识库",
      "status": "active",
      "source": "data/cosmological_simulation/generate_paper.jsonl",
      "index": "data/indexes/versions/<version>",
      "qa_count": 2402,
      "paper_count": 90
    }
  ],
  "count": 1
}
```

### 3.2 `search_knowledge`

检索 QA Pair 及其对应原文段落。

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `query` | `string` | 必填 | 检索问题或关键词，不能为空 |
| `knowledge_base_ids` | `string[] \| null` | `null` | 指定小方向知识库 ID；不传时只检索主库，传入后检索主库和指定小方向库 |
| `top_k` | `integer` | `10` | 返回条数，范围 1～100 |
| `min_score` | `number` | `0.0` | 最低综合排序分，阈值按实际查询和语料标定 |

调用示例：

```json
{
  "name": "search_knowledge",
  "arguments": {
    "query": "辐射输运如何影响再电离模拟？",
    "knowledge_base_ids": ["radiative_transfer"],
    "top_k": 5
  }
}
```

检索范围规则：

- 不传 `knowledge_base_ids` 或传空数组：只检索 `main`。
- 传入 `radiative_transfer` 等小方向 ID：检索 `main + radiative_transfer`。
- 传入多个 ID：检索 `main + 所有指定小方向库`，重复 ID 自动去重。
- 未知或禁用 ID 直接返回参数错误，不会静默扩大检索范围。

返回示例：

```json
{
  "query": "辐射输运如何影响再电离模拟？",
  "knowledge_base_ids": ["main", "radiative_transfer"],
  "matched": true,
  "results": [
    {
      "knowledge_base_id": "radiative_transfer",
      "knowledge_base_name": "辐射输运",
      "doc_id": "paper-or-document-id",
      "pair_id": 0,
      "question": "...",
      "answer": "...",
      "source_paragraph": "...",
      "source_section": "...",
      "source_page_start": null,
      "source_page_end": null,
      "score": 0.82,
      "score_components": {
        "bm25": 1.0,
        "tfidf": 0.6,
        "vector": 0.0,
        "rrf": 0.95,
        "rerank": 0.7
      }
    }
  ],
  "retrieval": {
    "fusion": "rrf",
    "rrf_k": 20,
    "generated_answer": false
  }
}
```

`source_paragraph` 优先来自 QA JSONL。主库缺少段落时，服务按命中的问答内容匹配
覆盖层中的 QA 版本，并选取该版本的可用证据。缺少证据时段落字段为空。

## 4. 小方向知识库配置

每个小方向使用与主库完全一致的 JSONL 格式。新增 `config/knowledge_bases/<id>.json`：

```json
{
  "id": "radiative_transfer",
  "name": "辐射输运",
  "description": "辐射输运和再电离相关 QA",
  "source": "data/knowledge_bases/radiative_transfer/source.jsonl",
  "index": "data/knowledge_bases/radiative_transfer/index",
  "enabled": true
}
```

源文件每行一个论文/文档对象：

```json
{
  "hash": "paper-or-document-id",
  "metadata": {
    "key": "10.xxxx/example",
    "title": "Paper title"
  },
  "result": {
    "qa_pairs": [
      {
        "question": "...",
        "answer": "...",
        "source_paragraph": "...",
        "source_section": "...",
        "source_page_start": null,
        "source_page_end": null
      }
    ]
  }
}
```

配置完成后重启 MCP 服务；索引可用 `qa_knowledge_mcp.build_kb` 按与主库相同的方式构建。

## 5. 调试请求

MCP Streamable HTTP 请求必须同时声明 JSON 和 SSE 响应类型，否则会收到 `Not Acceptable: Client must accept text/event-stream`。

用 Python MCP 客户端建立会话并查看工具列表。从 `qa_knowledge_mcp/` 运行：

```bash
uv run --locked python - <<'PY'
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    async with streamable_http_client("http://127.0.0.1:8001/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for tool in (await session.list_tools()).tools:
                print(tool.name)

asyncio.run(main())
PY
```

预期只包含：

```text
list_knowledge_bases
search_knowledge
```

工作台代理访问时，将地址中的 `http://127.0.0.1:8001/mcp` 替换为工作台提供的 `/proxy/8001/mcp` 地址，并保留上述 `Accept` 请求头。

## 6. 当前边界

- 只读检索，不提供写入、审核、重载、日报同步和自动回答工具。
- Topic、Decision、独立 Evidence 表暂作为内部迁移兼容数据，不作为 MCP 检索入口。
- 旧调用方如果仍调用已移除工具，需要迁移到 `list_knowledge_bases` 和 `search_knowledge`。
