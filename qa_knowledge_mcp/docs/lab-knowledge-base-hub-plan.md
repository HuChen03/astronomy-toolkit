# 文献中台驱动的 Linux 实验室知识库实施方案

## 1. 最终架构结论

根据现有文献中台 API，上一版“另建完整论文元数据主库、复制 PDF/Markdown、重新建设论文搜索”的设计应当调整。中台已经具备论文元数据、PDF、Markdown、全文状态、关键词/语义检索、引用网络、采集和自动化任务，因此它应当成为论文事实源。

新系统采用两类数据源：

1. **文献中台事实层**：论文 UUID、DOI/arXiv、作者、摘要、版本、PDF/Markdown 路径、采集状态、引用关系和搜索索引。
2. **实验室知识覆盖层**：收录理由、筛选状态、受控标签、阅读任务、结构化阅读卡、证据摘录、实验室共识、主题综述、项目决策和审核记录。

```text
              文献中台（论文事实源）
  搜索 / 读取 / 导入 / PDF / Markdown / 引用网络
                    │
                    │ hub paper UUID
                    ▼
       实验室知识覆盖层（本项目 SQLite + Markdown）
  Inbox / 标签 / 阅读卡 / 证据 / 共识 / 主题 / 审计
                    │
                    ├── test 原型改造后的知识加工 worker
                    ├── 111 的每日分类与快照能力
                    └── 实验室知识混合索引
                    │
                    ▼
              统一 Lab Knowledge MCP
```

基本原则：

- 中台 `paper_id` UUID 是实验室侧关联论文的首选外键。
- DOI、arXiv ID、PMID 和规范化标题只用于首次解析、去重校验和 UUID 失效恢复。
- 实验室侧不复制维护论文标题、摘要、PDF 路径等事实字段，只做短期缓存和历史快照。
- PDF 和 Markdown 仍由中台管理；知识加工 worker 通过 `/api/v1/read` 获取路径。
- 中台本地搜索负责“找论文”，本项目索引负责“找实验室知识和论文内证据”。
- MCP 是统一访问入口，但不是新的事实源；它负责调用中台并组合实验室知识。
- 第一版不依赖飞书、Notion、Obsidian 或 Zotero。

## 2. 三个现有项目的重新定位

| 项目 | 保留能力 | 不再承担 |
|---|---|---|
| 文献中台 | 论文事实库、附件、全文转换、搜索、在线发现、引用网络、采集任务 | 实验室阅读结论和项目决策 |
| `src/literature_digest_agent` | Daily Digest 客户端、实验室关键词与 LLM 分类、每日快照、日报查询 | 论文事实主库、PDF/Markdown 管理 |
| `pipelines/knowledge_acquisition` 与 `data/knowledge_acquisition` | 阅读卡和 QA 生成提示词、批处理经验、历史知识数据 | 生产目录、任务状态源、论文定位逻辑 |
| 当前项目 | 实验室覆盖层、知识加工任务、知识索引、统一 MCP | 复制中台论文库和附件库 |

`111` 不是必须位于最终请求链路中。它的分类和快照能力有价值，但 Daily Digest 已由中台生成，因此推荐把 `111` 改成内部的 `daily-curation` 模块或定时任务，最终不再单独暴露第二个 MCP。

## 3. 四层知识体系的实际归属

### 3.1 论文事实层：文献中台

以下字段只以中台为准：

- 中台论文 UUID。
- DOI、arXiv ID、PMID、标题、作者、摘要、期刊和发布日期。
- PDF 路径、Markdown 路径、`has_full_text` 和 `ingestion_status`。
- 中台搜索索引中的论文可用状态。
- 引用和被引查询结果及其中台缓存。
- 自动化采集任务和下载任务状态。

实验室侧可以保存 `paper_snapshot_json`，用于审计某次阅读或回答使用了什么元数据，但不得通过快照反向覆盖中台。

### 3.2 原文证据层：中台附件 + 实验室证据定位

PDF 和 Markdown 不搬入当前项目。实验室侧只记录：

```text
hub_paper_id
artifact_kind
artifact_path_snapshot
artifact_sha256
locator_quality
observed_at
```

其中路径只是服务器内部快照。MCP 不向普通客户端返回可任意访问的本地绝对路径，而返回论文 UUID、DOI/arXiv、页码、章节、图表和受控的内容片段。

知识 worker 调用 `/api/v1/read`：

- `markdown_path` 存在：读取 Markdown 并生成证据和阅读卡。
- 只有 `pdf_path`：允许 `/read` 触发 MinerU，任务稍后重试。
- 两者均不存在：状态设为 `fulltext_missing`，等待中台下载或人工上传。
- `has_full_text=false`：只能生成摘要级初筛信息，不得生成“全文阅读卡”。

需要检查 MinerU Markdown 是否保留页码标记。若不能恢复页码，则记录 `locator_quality=section_only`，回答中不得伪造页码。

### 3.3 结构化阅读卡层：实验室覆盖数据库

实验室侧 SQLite 建议使用 `data/lab_knowledge.sqlite3`，保存以下核心表：

```text
lab_papers
  hub_paper_id TEXT PRIMARY KEY,
  canonical_identifier TEXT,
  workflow_status TEXT,
  priority INTEGER,
  exclusion_reason TEXT,
  owner TEXT,
  first_seen_at TEXT,
  last_seen_at TEXT,
  metadata_snapshot_json TEXT,
  snapshot_at TEXT

discoveries
  discovery_id TEXT PRIMARY KEY,
  hub_paper_id TEXT,
  source TEXT,
  business_date TEXT,
  score REAL,
  reason TEXT,
  payload_json TEXT,
  created_at TEXT

tags
  tag_id TEXT PRIMARY KEY,
  name TEXT,
  prefix TEXT,
  description TEXT,
  active INTEGER

paper_tags
  hub_paper_id TEXT,
  tag_id TEXT,
  source TEXT,
  confidence REAL,
  actor TEXT,
  created_at TEXT

reading_cards
  card_id TEXT PRIMARY KEY,
  hub_paper_id TEXT,
  template_version TEXT,
  prompt_version TEXT,
  model TEXT,
  input_sha256 TEXT,
  status TEXT,
  card_json TEXT,
  rendered_markdown_path TEXT,
  reader TEXT,
  reviewer TEXT,
  created_at TEXT,
  reviewed_at TEXT

evidence_spans
  evidence_id TEXT PRIMARY KEY,
  hub_paper_id TEXT,
  card_id TEXT,
  stance TEXT,
  text TEXT,
  page_start INTEGER,
  page_end INTEGER,
  section TEXT,
  figure_ref TEXT,
  table_ref TEXT,
  locator_quality TEXT,
  source_sha256 TEXT,
  created_at TEXT

paper_relations
  source_hub_paper_id TEXT,
  target_hub_paper_id TEXT,
  relation_type TEXT,
  source TEXT,
  note TEXT,
  evidence_id TEXT

jobs
  job_id TEXT PRIMARY KEY,
  job_type TEXT,
  hub_paper_id TEXT,
  status TEXT,
  priority INTEGER,
  attempts INTEGER,
  max_attempts INTEGER,
  available_at TEXT,
  locked_by TEXT,
  locked_at TEXT,
  input_hash TEXT,
  config_json TEXT,
  result_json TEXT,
  error TEXT,
  created_at TEXT,
  updated_at TEXT

audit_log
  event_id TEXT PRIMARY KEY,
  actor TEXT,
  action TEXT,
  object_type TEXT,
  object_id TEXT,
  before_json TEXT,
  after_json TEXT,
  created_at TEXT
```

`lab_papers` 不是论文表，只是“中台论文在实验室流程中的投影”。不为作者、期刊、PDF 等建立另一套可编辑字段。

阅读卡必须区分：

- `author_claim`：作者原始主张。
- `reader_interpretation`：阅读者解释。
- `lab_consensus`：实验室复核后的观点。
- `conflicting_evidence`：反例或冲突证据。
- `model_summary`：尚未人工确认的模型概括。

AI 阅读卡状态只能从 `draft_ai` 开始，经人工变为 `pending_review`、`reviewed` 或 `rejected`。

### 3.4 主题综述与决策层：Git 友好 Markdown

```text
knowledge/
  topics/<topic-id>.md
  decisions/<decision-id>.md
  templates/reading-card.md
  vocabulary/tags.yaml
```

主题页通过 `hub_paper_ids` 引用中台论文：

```yaml
---
id: cosmological-simulation
title: 宇宙学数值模拟
maintainer: lab
status: active
last_reviewed: 2026-08-05
hub_paper_ids:
  - fd906a4a-4519-4678-9d47-4cbc9e62c2c5
---
```

同时保留 DOI/arXiv 作为可移植标识，以便未来中台迁移或 UUID 重建。

## 4. 中台 API 与知识库流程映射

| 中台接口 | 知识库用途 | 调用方 | 策略 |
|---|---|---|---|
| `/api/v1/search/offline` | 搜索中台已有论文 | MCP | 默认 `hybrid`，不重复建设论文搜索 |
| `/api/v1/search/online` | 本地无结果时在线发现 | MCP/管理员 | `save_to_library=false` 预览，确认后再保存 |
| `/api/v1/search/nasa-ads` | 天文方向联网发现 | MCP/定时任务 | 按需 ingest/download |
| `/api/v1/recommend/arxiv` | 最近 arXiv 新论文推荐 | 每日策展 | 适合补充 Daily Digest |
| `/api/v1/search/similar-pdf` | 从核心论文或自然语言扩展 related work | MCP/管理员 | 异步任务；下载须显示真实状态 |
| `/api/v1/read` | 获取论文事实和全文路径 | MCP/worker | 所有单篇事实读取的统一入口 |
| `/api/v1/digest/daily` | 每日候选、排序和摘要 | `111`/定时任务 | 先检查自动化任务，再生成快照 |
| `/api/v1/automation/jobs` | 判断上游采集是否仍在运行 | 定时任务/MCP | 上游运行中时延后发布日报 |
| `/api/v1/import/pdfs` | 导入实验室合法持有的 PDF | 管理 MCP/CLI | 仅接受服务端允许目录 |
| `/api/v1/markdown/backfill/by-dir` | 回填历史 Markdown | 迁移 CLI | 必须先 `dry_run=true` |
| `/api/v1/import/metadata/records/enrich` | 正式抓取前补全元数据 | 管理任务 | 不下载、不入库，适合预检 |
| `/api/v1/import/metadata/records/stream` | DOI/闭源/出版社批量获取 | Mac 编排器 | NDJSON 流必须持久化断点和结果 |
| `/api/v1/import/aps/batch-round` | APS 手工补采或运维 | 管理任务 | 日常优先使用已有自动化任务 |
| `/api/v1/papers/references` | 获取参考文献 | MCP/关系同步任务 | 写入实验室关系表时标记来源 |
| `/api/v1/papers/citations` | 获取被引论文 | MCP/关系同步任务 | 按需缓存，避免全库高频刷新 |
| `/api/v1/import/textbooks` | 教材导入 | 独立管理工具 | 与论文知识空间分开 |
| `/api/v1/search/textbook` | 教材 RAG | MCP | 作为独立工具，不混入论文证据排名 |
| `/api/v1/import/textbooks/retry-failed` | 教材失败重试 | 管理工具 | 仅管理员可用 |

### 4.1 不应重复开发的能力

- 不在本项目复制 `papers` 全量元数据表。
- 不复制 PDF 和 Markdown 文件。
- 不再建立第二套论文级 Meilisearch/Qdrant/向量库。
- 不自行调用 Semantic Scholar 替代中台的在线搜索和引用接口。
- 不自行实现出版社下载器。
- 不把中台本地绝对路径直接暴露给远程 MCP 用户。

### 4.2 中台尚需补充或确认的接口能力

现有接口足够启动第一版，但生产化前建议增加或确认：

1. **统一异步任务查询接口**：不应要求远程调用者读取 `task_path` 本地文件；建议 `GET /api/v1/tasks/{task_id}`。
2. **批量读取接口**：按 UUID 批量返回论文状态，减少 worker 对 `/read` 的 N 次调用。
3. **变更游标接口**：按 `updated_at` 或递增游标获取论文变化，替代全库扫描。
4. **健康检查接口**：区分数据库、Meilisearch、Qdrant、MinerU 和下载 worker 状态。
5. **API 认证与服务身份**：至少支持服务令牌；管理和只读权限分开。
6. **Markdown 转换状态**：明确 `queued/running/success/failed`，避免仅靠路径是否存在判断。
7. **文件内容指纹**：`/read` 最好返回 PDF/Markdown SHA-256 和转换版本。
8. **版本/更正/撤稿字段**：当前接口未显示完整支持，应作为后续元数据增强项。
9. **受控内容读取接口**：如果 MCP 与中台不在同一主机，需按论文 UUID 获取授权文本，而不是共享绝对路径。

在这些接口未补齐前，可以由同机 worker 读取路径；但此实现必须视为部署约束，而不是公开 API 契约。

## 5. 每日闭环流程

### 5.1 自动发现

建议每天 Asia/Shanghai 08:00 后执行：

```text
GET automation/jobs
  ├─ active job 仍 running → 延后 15～30 分钟
  └─ 可发布
       ↓
POST digest/daily
       ↓
111 受控类别分类与实验室优先级
       ↓
upsert lab_papers + discoveries
       ↓
写入 status=inbox
```

可按研究方向补充：

- 通用方向使用 `/search/online`。
- 天文方向使用 `/search/nasa-ads`。
- arXiv 新论文使用 `/recommend/arxiv`。
- 核心论文扩展使用 `/search/similar-pdf`。

这些结果先进入发现记录，不应默认全部下载和生成阅读卡。

### 5.2 人工筛选

状态机：

```text
inbox
  ├─ rejected            # 必须记录排除理由
  ├─ watch               # 只保留元数据并关注引用/版本
  ├─ queued_reading      # 进入全文准备
  └─ core                # 核心论文，优先加工和定期复核
```

日报同步只能创建新论文或更新 `last_seen_at`，不能覆盖人工状态、负责人、共识和人工标签。

### 5.3 全文准备

对 `queued_reading/core` 论文调用 `/read`：

```text
markdown ready → enqueue extract_reading_card
pdf only       → 等待 MinerU；定时重新读取
no fulltext    → fulltext_missing
```

对于 `fulltext_missing`：

1. arXiv 或已支持自动下载的论文交由中台服务器处理。
2. 实验室已有 PDF 使用 `/import/pdfs`。
3. 已有 Markdown 使用 backfill，并先 dry-run。
4. 闭源出版社任务通过 metadata stream 发送到江湾 Mac mini。
5. 遇到人工验证或限流，状态保持 `awaiting_acquisition`，不得标记失败完成。

### 5.4 知识加工

把 `test` 中脚本迁入当前项目的生产包：

```text
qa_knowledge_mcp/
  hub/
    client.py
    models.py
  curation/
    daily.py
    screening.py
  processing/
    worker.py
    reading_card.py
    qa_generator.py
    evidence.py
  storage/
    database.py
    repository.py
    migrations/
  indexing/
    chunks.py
    hybrid.py
```

任务类型：

- `refresh_paper_snapshot`
- `wait_for_markdown`
- `extract_reading_card`
- `extract_evidence`
- `generate_qa`
- `refresh_relations`
- `build_knowledge_chunks`
- `publish_index`

每个模型任务使用 `job_type + hub_paper_id + source_sha256 + prompt_version` 作为幂等键。重复执行不得重复调用模型。

阅读卡生成改为严格 JSON Schema，然后渲染 Markdown。必须保存模型、提示词版本、全文哈希、生成时间和审核状态。

### 5.5 主题更新

每周组会处理：

- `pending_review` 阅读卡。
- 同一主题的支持证据和冲突证据。
- 新增引用/被引关系中值得进入 Inbox 的论文。
- 项目技术路线和“不采用某方法”的决策记录。

主题 Markdown 和决策 Markdown 进入实验室知识索引，但回答时必须明确它们是实验室观点，不是论文原文。

## 6. 检索职责划分

### 6.1 中台搜索

以下查询直接调用中台：

- “本地有哪些 kagome superconductor 论文？”
- “找与这篇 PDF 相似的工作。”
- “在线找最近的 VLA manipulation 论文。”
- “这篇论文引用了什么？”
- “哪些论文引用了这篇论文？”
- “教材中如何解释单周期数据通路？”

### 6.2 实验室知识搜索

当前项目只索引：

- 阅读卡。
- 证据摘录。
- 历史 QA。
- 主题综述。
- 决策记录。
- 经筛选的 Markdown 正文块，可选。

统一 chunk 结构：

```text
chunk_id
hub_paper_id
source_type
text
page_start/page_end
section/figure/table
stance
review_status
access_level
source_sha256
content_hash
```

检索顺序：

```text
访问级别 + workflow_status + tag + source_type 预过滤
  → BM25
  → 向量召回
  → 合并去重
  → rerank
  → reviewed/证据定位质量加权
  → 返回中台 UUID 和稳定标识
```

中台 Qdrant 与本项目向量索引服务不同目的：前者找论文，后者找实验室知识和论文内证据，因此不是重复建设。

## 7. 统一 MCP 工具设计

### 7.1 论文发现与读取

```text
search_library(query, mode, page, per_page)
search_online(query, source, limit, save_to_library)
find_related(text, hub_paper_id, top_k, download_online)
get_paper(hub_paper_id|doi|arxiv_id|title)
get_references(hub_paper_id|doi)
get_citations(hub_paper_id|doi)
get_daily_digest(date, discipline, tags, limit)
recommend_recent_arxiv(query, since, until, top_k)
search_textbooks(query, top_k)
```

MCP 对中台结果做字段清洗，默认移除 `pdf_path`、`markdown_path`、`task_path` 和内部错误堆栈。

### 7.2 实验室知识

```text
search_lab_knowledge(question, filters, top_k)
get_reading_card(hub_paper_id)
get_paper_evidence(hub_paper_id, page, section)
list_topics()
get_topic(topic_id)
get_lab_paper_status(hub_paper_id)
knowledge_base_stats()
get_processing_status(hub_paper_id)
```

### 7.3 管理工具

默认关闭，使用独立管理员令牌：

```text
set_screening_status(hub_paper_id, status, reason, actor)
set_paper_tags(hub_paper_id, tags, actor)
assign_reader(hub_paper_id, reader)
enqueue_processing(hub_paper_id, stages)
review_reading_card(card_id, decision, actor)
import_pdf_directory(approved_path, tags)
start_markdown_backfill(approved_path, dry_run)
refresh_daily_catalog(date, force)
publish_knowledge_index()
```

闭源批量下载、浏览器验证和出版社编排不应由普通远程 MCP 工具直接触发。它们由管理员在 Mac mini 上运行受控 CLI，MCP 只显示状态。

### 7.4 带证据回答

如果增加 `answer_with_evidence`，输出至少包含：

```json
{
  "answer": "...",
  "confidence": "low|medium|high",
  "claims": [
    {
      "text": "...",
      "stance": "paper_claim|lab_consensus|model_summary",
      "evidence_ids": ["..."]
    }
  ],
  "papers": [
    {
      "hub_paper_id": "...",
      "doi": "...",
      "arxiv_id": "...",
      "pages": [12],
      "locator_quality": "page"
    }
  ],
  "retrieved_at": "...",
  "knowledge_index_version": "..."
}
```

没有证据时明确返回“不足以回答”，不能只依赖模型常识。

## 8. Linux 和 Mac mini 部署边界

### 8.1 qz Linux 服务器

运行：

- 文献中台数据库和 API。
- Meilisearch、Qdrant 和自动化 arXiv/APS 任务。
- `lab-knowledge-mcp.service`。
- `lab-knowledge-worker.service`。
- `lab-daily-curation.timer`。
- 实验室 SQLite、主题 Markdown、知识索引和备份。

推荐目录：

```text
/opt/lab-kb/app/
/srv/lab-kb/data/lab_knowledge.sqlite3
/srv/lab-kb/data/indexes/
/srv/lab-kb/knowledge/
/srv/lab-kb/backups/
/etc/lab-kb/lab-kb.env
/var/log/lab-kb/
```

MCP 和 worker 通过 `http://127.0.0.1:8080` 调用中台。MCP 监听 `127.0.0.1:8001`，由 Nginx/Caddy 提供 HTTPS、认证和限流，不能直接暴露公网端口。

### 8.2 江湾 Mac mini

运行：

- 需要复旦 IP、真实 Chrome、登录态和人工验证的 publisher 下载任务。
- metadata records stream 的断点编排脚本。
- ScienceDirect 等浏览器预热和人工接管。

Mac 不保存实验室知识主库。它只消费中台队列并把下载结果回写中台，避免产生第二套数据孤岛。

### 8.3 配置

```bash
LAB_KB_DATABASE=/srv/lab-kb/data/lab_knowledge.sqlite3
LAB_KB_KNOWLEDGE_ROOT=/srv/lab-kb/knowledge
LAB_KB_INDEX_ROOT=/srv/lab-kb/data/indexes
LAB_KB_HUB_BASE_URL=http://127.0.0.1:8080
LAB_KB_HUB_TOKEN=...
LAB_KB_MCP_HOST=127.0.0.1
LAB_KB_MCP_PORT=8001
LAB_KB_ADMIN_TOKEN=...
LAB_KB_TIMEZONE=Asia/Shanghai
LAB_KB_EMBEDDING_MODEL=/opt/models/bge-small-zh-v1.5
LAB_KB_LLM_BASE_URL=...
LAB_KB_LLM_API_KEY=...
LAB_KB_LLM_MODEL=...
```

SQLite 使用 WAL、`busy_timeout` 和定期 checkpoint。MCP 只读请求与 worker 写入通过短事务协作。

## 9. 现有知识迁移方案

现有宇宙学 90 篇论文和 2402 条 QA 可直接作为第一批正式数据，但必须先绑定中台 UUID。

### 9.1 论文和 Markdown 对齐

1. 汇总历史论文 DOI、arXiv、PMID、标题和 Markdown 路径。
2. 对已有 Markdown 目录调用 `/api/v1/markdown/backfill/by-dir`，先 `dry_run=true`。
3. 审核 `summary.json`、`updated.jsonl`、`created.jsonl` 和 `errors.jsonl`。
4. 修复标题错误、DOI 大小写重复和误匹配。
5. 小批量设置 `dry_run=false`，再全量正式回填。
6. 对每篇历史论文调用 `/read`，保存中台 UUID 和元数据快照。

注意：`create_missing=true` 会创建 md-only 论文，正式迁移前必须审查 dry-run，避免错误 Markdown 生成错误论文记录。

### 9.2 知识导入

1. `core_papers.json` 的每篇论文映射到 `hub_paper_id`。
2. `*.knowledge.md` 导入 `reading_cards`，状态标为 `legacy_unreviewed`。
3. 2402 条 QA 导入知识 chunk，每条写入 `hub_paper_id`、旧 `doc_id` 和 `pair_id`。
4. 原始 Markdown 计算 SHA-256，作为知识生成输入版本。
5. 为全部论文增加 collection `cosmological-simulation`。
6. 建立固定回归问题集，比较旧索引和新索引 Top-5。

迁移验收：

```text
hub_paper_count = 90
qa_count = 2402
qa_without_hub_paper = 0
duplicate_hub_paper = 0
knowledge_card_without_hub_paper = 0
old_query_top5_coverage >= 95%
```

## 10. 分阶段实施计划

### 阶段 0：中台契约确认，1～2 天

- 确认中台认证、超时、并发和错误返回约定。
- 验证 `/read` 触发 MinerU 后的状态变化。
- 检查 Markdown 页码标记和同机路径访问权限。
- 确认异步任务状态目前是 API 查询还是本地任务文件。

验收：使用 3 篇论文跑通搜索、读取、Markdown 等待、引用和被引查询。

### 阶段 1：中台客户端与实验室覆盖库，3～5 天

- 在当前项目实现 typed hub client、重试、超时和响应清洗。
- 建立实验室 SQLite schema 和 migration。
- 使用中台 UUID 实现 Inbox、状态、标签、负责人和审计。
- MCP 增加 `search_library`、`get_paper` 和实验室状态工具。

验收：不复制论文事实字段；同一 UUID 多次同步只产生一条实验室记录；中台暂时不可用时返回清晰错误。

### 阶段 2：每日发现整合，2～4 天

- 复用 `111` 的 Daily Digest 客户端和分类逻辑。
- 保存每日 discovery 快照并幂等进入 Inbox。
- 增加 automation job 运行中延迟策略。
- 接入 arXiv 推荐，天文方向按需接入 NASA ADS。

验收：重复运行不覆盖人工状态；日报候选、分类理由和上游分数可追溯。

### 阶段 3：历史迁移，3～5 天

- dry-run Markdown backfill，并处理冲突。
- 将 90 篇论文绑定中台 UUID。
- 导入 2402 条 QA 和历史知识卡。
- 建立迁移报告和回归问题集。

验收：所有 QA 和知识卡均关联中台论文，数量和召回达到迁移指标。

### 阶段 4：后台知识加工，5～8 天

- 将 `test` 抽取逻辑改造成 SQLite 任务 worker。
- 实现 `/read` 全文状态轮询、哈希幂等和失败重试。
- 生成结构化阅读卡、证据和 QA。
- 增加人工审核和任务死信查询。

验收：5 篇新论文完整跑通；重复任务不重复调用模型；无全文论文不会生成伪全文卡片。

### 阶段 5：统一检索与 MCP，4～7 天

- 索引阅读卡、证据、QA、主题页和可选正文块。
- 实现权限、审核状态、来源类型和标签预过滤。
- 实现版本化索引、原子切换和回滚。
- 统一代理中台搜索、引用、教材和日报工具。

验收：论文搜索走中台，实验室知识搜索走本项目；重要结论返回 UUID、稳定标识和页码/章节。

### 阶段 6：生产部署，2～4 天

- 配置 systemd、反向代理、TLS、令牌和日志轮转。
- 配置 SQLite/Markdown/索引备份和恢复演练。
- 运行 7 天双服务观察期，再下线 `111` 独立 MCP。
- 保留旧 QA MCP 一周只读回滚入口。

整体代码实施约 3～5 周，流程稳定和标签调整仍建议观察 6～8 周。

## 11. 日常维护和验收指标

### 每日

- 检查中台自动化任务。
- 生成 Daily Digest 并同步 Inbox。
- 处理已批准论文的全文等待和知识任务。
- 发布通过校验的新知识索引。

### 每周

- 人工筛选 Inbox。
- 审核 AI 阅读卡。
- 更新主题综述和冲突证据。
- 查看中台下载 pending、人工验证和知识任务死信。

### 每月

- 清理标签和重复实验室投影。
- 刷新核心论文引用/被引关系。
- 检查元数据更正、版本和撤稿能力覆盖。
- 导出实验室覆盖数据库、知识 Markdown 和索引 manifest。

### 核心指标

- `lab_papers` 中中台 UUID 完整率 100%。
- 核心论文阅读卡覆盖率 100%。
- AI 阅读卡人工审核率 100%。
- 重要结论证据定位覆盖率 100%。
- 历史 90 篇论文和 2402 条 QA 无孤立记录。
- 日报重复运行不覆盖人工字段。
- 中台短时不可用不会破坏实验室数据库和当前索引。
- MCP 不泄露服务器绝对路径、API 密钥和受限全文。
- 备份可在空目录恢复 SQLite、主题页和知识索引。

## 12. 第一批开发任务

1. `hub-client`：封装 search、read、digest、references、citations 和任务错误。
2. `overlay-schema`：实验室状态、标签、卡片、证据、任务和审计表。
3. `mcp-paper-tools`：中台搜索和读取的安全代理工具。
4. `daily-curation`：把 `111` 分类和快照能力迁入当前项目。
5. `legacy-backfill`：历史 Markdown dry-run 报告和冲突处理。
6. `legacy-migration`：90 篇论文、2402 条 QA 和知识卡绑定 UUID。
7. `processing-worker`：全文等待、幂等、重试和死信。
8. `reading-card-v2`：严格 JSON、证据定位、Markdown 渲染和审核。
9. `knowledge-index-v2`：多来源 chunk、过滤、版本发布和回滚。
10. `mcp-knowledge-tools`：阅读卡、证据、主题、状态和带出处回答。
11. `security`：令牌、路径清洗、访问级别和审计。
12. `operations`：systemd、反向代理、备份、恢复和健康检查。

完成后，数据责任边界非常清晰：文献中台回答“论文是什么、文件在哪里、与哪些论文有关”，实验室覆盖层回答“为什么收录、谁读过、证据支持什么、实验室如何判断”，统一 MCP 负责把两者安全组合为可追溯的服务。
