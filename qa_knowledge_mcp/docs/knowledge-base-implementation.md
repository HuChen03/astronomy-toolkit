# 当前项目知识库实施方案

> **当前运行边界（2026-08-13）**：本文早期章节保留历史设计记录。当前运行时已拆为两个独立 MCP：
> `astronomy-knowledge`（8001，天文学/宇宙学知识库搜索）和 `daily-literature`（8002，每日论文）。
> 本文中涉及“统一 MCP”、日报工具注册和 Evidence Pack 工具注册的内容不再适用于当前服务。

## 1. 项目目标

当前项目 `qa_knowledge_mcp` 是一个部署在 Linux 服务器上的天文学知识库搜索服务，主要提供两项能力：

1. **QA Pair 检索**：从现有天文学/宇宙学 QA 知识库检索问题、答案和原文段落。
2. **小方向联合检索**：默认搜索主库，按参数将指定小方向知识库加入搜索范围。

项目不把 MCP 返回的检索结果直接描述成“模型已经验证的最终答案”。Evidence Pack 的职责是提供证据，上层 Agent 或调用方负责根据证据组织最终回答。

```text
每日论文数据 ───────────────┐
                            ├── Lab Knowledge MCP ── 外部 Agent / MCP 客户端
论文 QA JSONL ── 混合检索 ──┘
```

## 2. 当前完成情况

截至 2026 年 8 月 5 日，当前项目已经具备：

- 一个统一的 `lab-knowledge` MCP 服务。
- Streamable HTTP 和 stdio 两种运行方式。
- 每日论文查询、分类过滤和文本过滤。
- 每日论文 JSON 磁盘缓存。
- 每日任务状态查询。
- QA 知识库混合检索。
- 按论文聚合的 Evidence Pack。
- 论文标题、论文 key、类别和历史来源元数据。
- BM25、TF-IDF、可选 embedding/FAISS 和可选 CrossEncoder 重排。
- embedding 不可用时的自动降级。
- 旧版 QA 查询工具兼容。
- 全仓库 34 项单元测试和 MCP 工具调用测试。

当前知识库规模：

```text
论文数：90
QA 数：2402
主题：宇宙学数值模拟
```

## 3. 项目目录

```text
qa_knowledge_mcp/
├── qa_knowledge_mcp/
│   ├── knowledge_base.py       # QA 加载、混合检索、Evidence Pack
│   ├── daily_digest.py         # 每日论文获取、分类、过滤和缓存
│   ├── mcp_server.py           # 统一 MCP 工具注册
│   ├── build_kb.py             # 离线索引构建
│   └── query.py                # 本地命令行查询
├── config/
│   └── daily_categories.json   # 每日论文受控分类
├── data/
│   ├── cosmological_simulation/
│   │   ├── generate_paper.jsonl
│   │   ├── core_papers.json
│   │   └── index/
│   │       ├── chunks.jsonl
│   │       └── manifest.json
│   └── daily_digest_cache/     # 每日论文缓存
├── docs/
│   ├── mcp-api.md
│   └── knowledge-base-implementation.md
├── tests/
├── run_cosmological_mcp.sh
├── start_cosmological_mcp.sh
├── status_cosmological_mcp.sh
└── stop_cosmological_mcp.sh
```

## 4. 知识库数据格式

### 4.1 原始论文 QA

原始数据位于：

```text
data/cosmological_simulation/generate_paper.jsonl
```

每行对应一篇论文，包含论文元数据和多个 QA 对。

### 范例：一篇论文记录

```json
{
  "hash": "ecd05db06f805f5f042e33570097db9285ff3b2b617be8e1b33799095c150386",
  "metadata": {
    "rank": 1,
    "key": "10.1007_s41115-022-00015-5",
    "title": "Modeling cosmic reionization",
    "category": "综述与数值可靠性",
    "source": "/internal/path/10.1007_s41115-022-00015-5.md"
  },
  "result": {
    "qa_pairs": [
      {
        "question": "论文采用的默认宇宙学参数是什么？",
        "answer": "论文采用平直宇宙学，并给出了 Ω_M、Ω_Λ、Ω_b 和 H_0 等参数。"
      }
    ]
  }
}
```

字段含义：

| 字段 | 说明 |
|---|---|
| `hash` | 当前论文知识记录的稳定文档 ID |
| `metadata.rank` | 核心论文集中的历史排序 |
| `metadata.key` | 历史论文 key，通常由 DOI 转换而来 |
| `metadata.title` | 论文标题 |
| `metadata.category` | 论文所属知识类别 |
| `metadata.source` | 生成 QA 时使用的历史 Markdown 来源 |
| `result.qa_pairs` | 从论文中提取的问答证据 |

`metadata.source` 是内部历史信息，不应直接通过外部 MCP 返回。

### 4.2 标准化检索记录

离线构建后，每个 QA 对会转换成独立的检索记录：

```json
{
  "doc_id": "ecd05db...",
  "pair_id": 0,
  "question": "论文采用的默认宇宙学参数是什么？",
  "answer": "论文采用平直宇宙学……",
  "source_file": "data/cosmological_simulation/generate_paper.jsonl",
  "source_line": 1,
  "status": "done",
  "paper_key": "10.1007_s41115-022-00015-5",
  "paper_title": "Modeling cosmic reionization",
  "paper_category": "综述与数值可靠性",
  "paper_rank": 1
}
```

标准化记录位于：

```text
data/cosmological_simulation/index/chunks.jsonl
```

### 4.3 论文 key 与 DOI

历史 `paper_key` 通常使用下划线代替 DOI 中的第一个 `/`：

```text
paper_key: 10.1046_j.1365-8711.2000.03673.x
DOI:       10.1046/j.1365-8711.2000.03673.x
```

Evidence Pack 会在可以可靠转换时同时返回 `paper_key` 和 `doi`。

## 5. 检索架构

当前知识检索使用混合召回：

```text
query
  │
  ├── BM25 关键词检索
  ├── TF-IDF 稀疏向量检索
  ├── 可选 embedding + FAISS
  └── 轻量重排或可选 CrossEncoder
          │
          ▼
      候选 QA 排序
          │
          ▼
     按论文限制数量
          │
          ▼
      Evidence Pack
```

### 5.1 当前默认模式

启动脚本默认设置：

```bash
QA_ENABLE_EMBEDDING=false
QA_ENABLE_RERANKER=false
```

因此默认实际使用：

```text
BM25 + TF-IDF + 轻量重排
```

该模式适合 CPU 服务器，启动稳定，不需要在线下载模型。

### 5.2 可选向量模式

服务器已有本地模型并且资源允许时，可以启用：

```bash
export QA_ENABLE_EMBEDDING=true
export QA_EMBEDDING_MODEL=/path/to/bge-small-zh-v1.5
export QA_EMBEDDING_DEVICE=cpu
export QA_EMBEDDING_BATCH_SIZE=8
```

先离线构建索引：

```bash
python3 -m qa_knowledge_mcp.build_kb \
  data/cosmological_simulation/generate_paper.jsonl \
  --output-dir data/cosmological_simulation/index \
  --model /path/to/bge-small-zh-v1.5 \
  --device cpu \
  --batch-size 8
```

生成：

```text
chunks.jsonl
embeddings.npy
faiss.index
manifest.json
```

## 6. Evidence Pack

Evidence Pack 是当前知识库最重要的输出格式。

它解决的问题是：

- 找到与 query 最相关的现有知识。
- 避免结果全部来自同一篇论文。
- 给每条证据稳定编号。
- 返回论文信息和检索分数。
- 明确结果是检索证据，而不是新生成答案。

### 6.1 范例：输入问题

```text
宇宙学模拟中如何控制二体弛豫和数值分辨率误差？
```

MCP 调用参数：

```json
{
  "name": "build_evidence_pack",
  "arguments": {
    "query": "宇宙学模拟中如何控制二体弛豫和数值分辨率误差？",
    "top_k": 5,
    "max_per_paper": 2,
    "min_score": 0.1
  }
}
```

### 6.2 范例：Evidence Pack

```json
{
  "query": "宇宙学模拟中如何控制二体弛豫和数值分辨率误差？",
  "matched": true,
  "evidence_count": 2,
  "paper_count": 2,
  "evidence": [
    {
      "evidence_id": "5dcc2fa1...:0",
      "paper_id": "5dcc2fa1...",
      "paper_key": "10.1046_j.1365-8711.2000.03673.x",
      "doi": "10.1046/j.1365-8711.2000.03673.x",
      "paper_title": "On the effects of resolution in dissipationless cosmological simulations",
      "paper_category": "综述与数值可靠性",
      "question": "论文研究的核心数值问题是什么？",
      "evidence_text": "论文重点考察力分辨率、软化尺度、时间步长和不同 N 体算法的影响……",
      "score": 0.620944,
      "score_components": {
        "bm25": 50.258796,
        "vector": 0.0,
        "rerank": 65.0
      },
      "source": {
        "source_line": 2,
        "pair_id": 0,
        "locator_quality": "qa_pair"
      }
    },
    {
      "evidence_id": "862fb810...:2",
      "paper_id": "862fb810...",
      "paper_key": "10.1046_j.1365-8711.2002.05400.x",
      "doi": "10.1046/j.1365-8711.2002.05400.x",
      "paper_title": "Two-body relaxation in cosmological simulations",
      "paper_category": "综述与数值可靠性",
      "question": "如何利用双质量粒子检验两体弛豫？",
      "evidence_text": "如果演化严格无碰撞，两类粒子的最终空间分布应与粒子质量无关……",
      "score": 0.595735,
      "score_components": {
        "bm25": 53.585717,
        "vector": 0.0,
        "rerank": 43.0
      },
      "source": {
        "source_line": 5,
        "pair_id": 2,
        "locator_quality": "qa_pair"
      }
    }
  ],
  "papers": [
    {
      "paper_id": "5dcc2fa1...",
      "paper_key": "10.1046_j.1365-8711.2000.03673.x",
      "doi": "10.1046/j.1365-8711.2000.03673.x",
      "title": "On the effects of resolution in dissipationless cosmological simulations",
      "category": "综述与数值可靠性",
      "rank": 2,
      "evidence_ids": ["5dcc2fa1...:0"]
    }
  ],
  "provenance": {
    "source_file": "data/cosmological_simulation/generate_paper.jsonl",
    "retrieval": "hybrid_bm25_tfidf_vector_rerank",
    "generated_answer": false
  }
}
```

### 6.3 如何理解返回结果

- `evidence_id`：证据唯一标识，由 `doc_id:pair_id` 组成。
- `paper_id`：当前知识库内部论文文档 ID。
- `paper_key`：历史稳定论文 key。
- `doi`：从 `paper_key` 可可靠恢复时返回。
- `question`：生成知识库时提取的问题。
- `evidence_text`：该问题对应的现有答案。
- `score`：综合相关度，用于结果排序。
- `locator_quality=qa_pair`：当前出处粒度为 QA 对，还不是 PDF 页码。
- `generated_answer=false`：本次没有调用模型生成最终答案。

### 6.4 范例：上层 Agent 如何回答

上层 Agent 可以根据 Evidence Pack 组织为：

```text
在宇宙学 N 体模拟中，控制二体弛豫需要同时考虑质量分辨率、力分辨率、
软化尺度和时间积分精度。力分辨率远小于平均粒子间距时，非物理二体散射
可能增强；时间步长误差还会放大该问题 [evidence: 5dcc2fa1...:0]。

双质量粒子测试可用于检查质量分凝：如果重粒子向中心下沉、轻粒子更容易
逸出，说明模拟中存在明显的碰撞弛豫 [evidence: 862fb810...:2]。

参考论文：
1. On the effects of resolution in dissipationless cosmological simulations
2. Two-body relaxation in cosmological simulations
```

要求：

1. 每个重要结论保留 `evidence_id`。
2. 不把无证据的模型常识加入答案。
3. `matched=false` 时明确说明当前知识库没有足够证据。
4. 当前不要声称证据定位到了具体 PDF 页码。

## 7. 每日论文能力

当前项目通过同一个 MCP 服务提供每日论文列表。

支持：

- 指定日期。
- 使用受控分类过滤。
- 使用 query 对标题、摘要、概括和作者进行文本过滤。
- 按优先级和原始相关度排序。
- 将每日结果缓存到本地磁盘。
- 数据暂不可用时返回结构化状态，而不是让整个 MCP 失败。

### 7.1 日报分类

分类配置位于：

```text
config/daily_categories.json
```

### 范例：增加一个分类

```json
{
  "id": "numerical_cosmology",
  "name": "数值宇宙学",
  "definition": "宇宙学数值方法、N 体和流体模拟相关论文。",
  "terms": [
    "numerical cosmology",
    "cosmological simulation",
    "n-body simulation",
    "hydrodynamical simulation",
    "数值宇宙学"
  ],
  "weight": 6,
  "match_mode": "any",
  "enabled": true
}
```

字段说明：

- `id`：稳定分类 ID，MCP 参数使用此值。
- `name`：展示名称。
- `definition`：分类含义。
- `terms`：不区分大小写的匹配词。
- `weight`：匹配后增加的优先级。
- `match_mode=any`：命中任意词即可。
- `match_mode=all`：需要命中全部词。
- `enabled=false`：暂时停用分类。

修改后重启 MCP 即可重新加载分类。

### 7.2 范例：查询每日宇宙学论文

```json
{
  "name": "get_daily_digest",
  "arguments": {
    "date": "2026-08-05",
    "category_ids": ["cosmological_simulation"],
    "query": "simulation",
    "limit": 10,
    "force_refresh": false
  }
}
```

返回示例：

```json
{
  "status": "success",
  "date": "2026-08-05",
  "items": [
    {
      "paper_id": "paper-uuid",
      "title": "A New Cosmological Simulation Method",
      "authors": ["Author A", "Author B"],
      "summary": "论文概括",
      "doi": "10.xxxx/example",
      "arxiv_id": null,
      "venue": "Example Journal",
      "published_at": "2026-08-05",
      "score": 0.91,
      "priority_score": 6.91,
      "categories": [
        {
          "id": "cosmological_simulation",
          "name": "宇宙学数值模拟",
          "matched_terms": ["cosmological simulation"],
          "score": 6.0
        }
      ]
    }
  ],
  "returned": 1,
  "matched_total": 1,
  "cache_hit": false
}
```

### 7.3 本地缓存

缓存目录：

```text
data/daily_digest_cache/<discipline>/<date>.json
```

范例：

```text
data/daily_digest_cache/cond-mat/2026-08-05.json
```

行为：

- 默认优先读取缓存。
- `force_refresh=true` 时重新获取当日数据。
- 修改分类配置不需要删除缓存，因为分类在读取时重新计算。
- 已有缓存时，即使新数据暂时不可获取，也可以继续查询历史日报。

## 8. 本地命令行范例

### 8.1 查询知识库

```bash
python3 -m qa_knowledge_mcp.query \
  "宇宙学模拟中如何控制二体弛豫？" \
  --source data/cosmological_simulation/generate_paper.jsonl \
  --index data/cosmological_simulation/index \
  --top-k 5
```

### 8.2 查看知识库统计

```bash
QA_ENABLE_EMBEDDING=false python3 - <<'PY'
from pathlib import Path
from qa_knowledge_mcp.knowledge_base import KnowledgeBase

kb = KnowledgeBase(
    Path("data/cosmological_simulation/generate_paper.jsonl"),
    Path("data/cosmological_simulation/index"),
)
print(kb.stats())
PY
```

预期关键字段：

```json
{
  "record_count": 2402,
  "doc_count": 90,
  "has_bm25_index": true,
  "has_sparse_index": true,
  "has_faiss_index": false
}
```

### 8.3 直接构建 Evidence Pack

```bash
QA_ENABLE_EMBEDDING=false python3 - <<'PY'
import json
from pathlib import Path
from qa_knowledge_mcp.knowledge_base import KnowledgeBase

kb = KnowledgeBase(
    Path("data/cosmological_simulation/generate_paper.jsonl"),
    Path("data/cosmological_simulation/index"),
)
pack = kb.evidence_pack(
    "弱引力透镜模拟有哪些主要数值误差？",
    top_k=5,
    max_per_paper=2,
)
print(json.dumps(pack, ensure_ascii=False, indent=2))
PY
```

## 9. 添加新论文知识的范例

当前知识库的增量输入格式仍然是 JSONL。

### 9.1 准备一条新论文记录

```json
{
  "hash": "new-paper-content-sha256",
  "metadata": {
    "rank": 91,
    "key": "10.1234_example-paper",
    "title": "Example Paper",
    "category": "数值方法",
    "source": "/internal/path/example-paper.md"
  },
  "result": {
    "qa_pairs": [
      {
        "question": "该论文解决了什么问题？",
        "answer": "该论文研究……"
      },
      {
        "question": "该方法的主要限制是什么？",
        "answer": "该方法依赖……"
      }
    ]
  }
}
```

将其作为一行追加到：

```text
data/cosmological_simulation/generate_paper.jsonl
```

注意：实际写入必须输出单行 JSON，不能使用上面的多行展示格式。

### 9.2 重建轻量索引

```bash
python3 -m qa_knowledge_mcp.build_kb \
  data/cosmological_simulation/generate_paper.jsonl \
  --output-dir data/cosmological_simulation/index \
  --no-embedding
```

### 9.3 重新加载服务

方式一，调用 MCP：

```text
reload_knowledge_base()
```

方式二，重启服务：

```bash
./stop_cosmological_mcp.sh
./start_cosmological_mcp.sh
```

### 9.4 验证新论文

```text
1. 调用 knowledge_base_stats，确认 record_count 增加。
2. 使用新论文中的术语调用 build_evidence_pack。
3. 检查 paper_title、paper_key 和 evidence_id。
4. 检查旧的固定测试 query 仍能召回原结果。
```

## 10. 启动和部署

### 10.1 前台启动

```bash
cd /path/to/astronomy-toolkit/qa_knowledge_mcp
./run_cosmological_mcp.sh
```

### 10.2 后台启动

```bash
./start_cosmological_mcp.sh
./status_cosmological_mcp.sh
```

停止：

```bash
./stop_cosmological_mcp.sh
```

### 10.3 默认服务地址

```text
http://<服务器IP>:8001/mcp
```

### 10.4 查看工具

```bash
curl -sS -X POST http://127.0.0.1:8001/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

应该包含：

```text
build_evidence_pack
get_daily_digest
get_daily_sync_status
get_knowledge_record
knowledge_base_stats
list_daily_categories
query_knowledge
reload_knowledge_base
```

## 11. 环境变量

| 环境变量 | 默认值 | 作用 |
|---|---|---|
| `QA_SOURCE` | `data/cosmological_simulation/generate_paper.jsonl` | 原始 QA 文件 |
| `QA_INDEX` | `data/cosmological_simulation/index` | 索引目录 |
| `QA_MCP_HOST` | `0.0.0.0` | MCP 监听地址 |
| `QA_MCP_PORT` | `8001` | MCP 端口 |
| `QA_ENABLE_EMBEDDING` | `false` | 是否启用向量检索 |
| `QA_ENABLE_RERANKER` | `false` | 是否启用 CrossEncoder |
| `QA_EMBEDDING_MODEL` | 本地模型路径 | embedding 模型 |
| `LDA_DISCIPLINE` | `cond-mat` | 每日论文方向参数 |
| `LDA_TIMEZONE` | `Asia/Shanghai` | 业务时区 |
| `LDA_CUTOFF_HOUR` | `8` | 每日日期截止小时 |
| `LDA_KEYWORDS_PATH` | `config/daily_categories.json` | 分类配置 |
| `LAB_DAILY_CACHE_DIR` | `data/daily_digest_cache` | 每日论文缓存 |

## 12. 测试

运行全部测试：

```bash
python3 -m unittest discover -s tests -v
```

当前覆盖：

- 中文和英文 QA 检索。
- Evidence Pack 论文元数据和 provenance。
- 离线 chunks 加载。
- 每日论文缓存。
- 每日分类过滤。
- 每日任务延迟状态。
- 不同每日数据返回格式的标准化。
- 统一 MCP 工具注册和调用。

新增功能时至少补充：

1. 正常输入测试。
2. 空结果测试。
3. 错误或不可用状态测试。
4. MCP 工具调用测试。

## 13. 当前限制

### 13.1 证据定位

当前证据只能定位到：

```text
JSONL source_line + QA pair_id
```

还不能定位到 PDF 页码、章节或图表。

### 13.2 论文标识

当前 `paper_id` 是历史 QA 文档 hash。虽然大部分记录有 DOI 形式的 `paper_key`，但尚未建立独立的论文标识映射表。

### 13.3 知识类型

当前 QA 没有严格区分：

- 作者原始主张。
- 模型概括。
- 阅读者解释。
- 实验室共识。
- 冲突证据。

### 13.4 权限

当前知识库没有按用户、课题组或项目进行检索前权限过滤。部署时应先通过反向代理限制服务访问范围。

### 13.5 最终回答

当前项目只提供 Evidence Pack，不提供 `answer_with_evidence`。这是有意设计：先保证证据检索稳定，再增加生成回答能力。

## 14. 后续实施顺序

### 阶段 1：证据定位升级

为 QA 增加：

```text
page_start
page_end
section
figure_ref
table_ref
locator_quality
```

范例：

```json
{
  "evidence_id": "doc-id:12",
  "evidence_text": "软化尺度过小会增加非物理散射……",
  "source": {
    "page_start": 8,
    "page_end": 9,
    "section": "3.2 Numerical Relaxation",
    "figure_ref": "Figure 4",
    "locator_quality": "page"
  }
}
```

### 阶段 2：结构化阅读卡

将单篇论文知识扩展为：

```text
论文解决的问题
核心贡献
方法与关键假设
数据集/实验环境
主要结果
作者声称的结论
证据真正支持的结论
局限性与潜在偏差
可复现性
与实验室工作的关系
相关或矛盾论文
可复用代码和数据
重要出处
阅读者、审核者和状态
```

### 阶段 3：知识类型区分

每条知识增加：

```text
author_claim
model_summary
reader_interpretation
lab_consensus
conflicting_evidence
```

AI 自动生成内容只能标记为 `model_summary` 或 `draft_ai`，不能直接成为实验室共识。

### 阶段 4：主题综述

增加：

```text
knowledge/topics/
knowledge/decisions/
```

主题页范例：

```markdown
# 宇宙学模拟中的数值可靠性

## 当前共识

软化尺度、粒子质量和时间步长必须联合收敛测试。

## 支持证据

- evidence-id-1
- evidence-id-2

## 冲突或边界

- 不同算法在高密度区可能表现不同。

## 对实验室项目的影响

- 所有正式模拟至少执行两档分辨率对比。

## 最近复核

2026-08-05
```

### 阶段 5：增量加工任务

增加 SQLite 任务表，实现：

```text
new paper
  → QA generation
  → evidence extraction
  → index build
  → index validation
  → atomic publish
```

任务必须使用输入哈希和提示词版本保证幂等，避免重复调用模型。

### 阶段 6：带证据回答

Evidence Pack 稳定后新增：

```text
answer_with_evidence(query)
```

输出范例：

```json
{
  "answer": "综合结论",
  "confidence": "high",
  "claims": [
    {
      "text": "关键结论",
      "evidence_ids": ["doc-id:1", "doc-id:5"]
    }
  ],
  "papers": [],
  "index_version": "2026-08-05T12:00:00Z"
}
```

最低要求：

- 每个重要结论关联证据。
- 没有足够证据时明确返回不知道。
- 保存检索时间和索引版本。
- 不把模型概括伪装成论文原话。

## 15. 验收指标

### 当前系统

- 90 篇论文全部可被索引。
- 2402 条 QA 数量保持一致。
- Evidence Pack 返回论文标题和稳定证据 ID。
- 单篇论文证据数量可以限制。
- 每日论文和知识检索使用同一个 MCP 地址。
- embedding 不可用时服务仍能启动。
- 数据暂不可用时返回结构化状态。
- 自动测试全部通过。

### 完整知识库

- 核心论文阅读卡覆盖率达到 100%。
- 重要证据页码或章节定位覆盖率达到 100%。
- AI 阅读卡人工审核率达到 100%。
- 重要回答证据引用覆盖率达到 100%。
- 新数据写入后可以安全重建并回滚索引。
- 新成员可以通过主题页快速理解研究方向。

## 16. 推荐的近期工作

建议按以下顺序继续：

1. 为 90 篇论文建立统一论文标识映射。
2. 从原始 Markdown 恢复章节和页码定位。
3. 为 Evidence Pack 增加 `page/section/figure/table`。
4. 迁移结构化阅读卡生成代码。
5. 建立增量任务和索引版本发布。
6. 增加主题综述 Markdown。
7. 最后增加 `answer_with_evidence`。

当前项目已经完成可用的第一阶段：每日论文负责发现，Evidence Pack 负责提供本地实验室知识证据。后续演进应继续围绕“出处更精确、知识类型更清楚、增量更新更可靠”展开。
