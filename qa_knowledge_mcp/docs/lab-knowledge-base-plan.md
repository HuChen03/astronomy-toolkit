# Linux 实验室论文知识库实施方案

> **已被中台版方案取代。** 在确认文献中台已经提供论文事实库、PDF/Markdown、
> 搜索、引用网络和采集任务后，不再建议复制建设完整论文主库。请以
> `docs/lab-knowledge-base-hub-plan.md` 为实施依据；本文仅保留为早期设计记录。

## 1. 结论与实施边界

当前三个目录已经覆盖了知识库闭环的大部分能力，但还没有统一的数据模型和任务编排：

| 现有项目 | 已有能力 | 在新系统中的定位 |
|---|---|---|
| `src/literature_digest_agent` | 每日论文拉取、关键词与 LLM 分类、SQLite 快照、日报 MCP | 论文发现器和 Inbox 数据源 |
| `pipelines/knowledge_acquisition` | Markdown 全文加工、知识卡生成、QA 生成、失败记录 | 后台知识加工流水线的原型 |
| 当前项目 | QA 规范化、BM25/TF-IDF/向量混合检索、MCP 服务 | 统一知识主库、检索索引和 MCP 出口 |

推荐目标不是继续长期维护两个独立 MCP，而是逐步收敛为：

```text
文献中台/API或人工导入
          │
          ▼
  111 每日发现与分类
          │ inbox sync
          ▼
  统一 SQLite 元数据主库 ───── PDF/Markdown 对象目录
          │                         │
          ├─ 人工筛选/状态维护       ├─ 文本转换
          │                         └─ 页码/章节定位
          ▼
  test 脚本改造后的后台任务队列
          │
          ├─ 结构化阅读卡
          ├─ 证据摘录
          ├─ QA/chunk
          └─ 主题综述素材
          │
          ▼
  当前项目的混合检索索引
          │
          ▼
       统一 MCP Server
```

第一版不依赖飞书、Notion、Obsidian 或另一个应用，也不强制依赖 Zotero。SQLite、Markdown、JSONL 和原始附件均保存在 Linux 文件系统中；MCP 是主要访问入口，CLI 是管理和灾备入口。未来如果实验室开始使用 Zotero，可将 Zotero Group Library 接成上游事实源，而不改变下游表结构和 MCP 协议。

## 2. 四层体系在本项目中的具体映射

### 2.1 论文元数据层

使用统一 SQLite 数据库 `data/lab_kb.sqlite3`，而不是让日报快照或 QA JSONL 充当事实源。

论文规范主键 `paper_id` 按以下优先级生成：

1. `doi:<规范化 DOI>`
2. `arxiv:<去版本号 arXiv ID>`
3. `pmid:<PMID>`
4. `title:<规范化标题 SHA-256>`

DOI 统一转小写，去掉 `https://doi.org/`、`doi:` 和首尾空白。arXiv 的 `v1`、`v2` 不进入作品主键，而进入版本表。所有来自 `111`、历史 QA 和人工导入的数据先经过同一个 normalizer，再执行 upsert。

建议核心表：

```text
papers
  paper_id, doi, arxiv_id, pmid, title, abstract, year,
  venue, authors_json, language, work_type, status,
  retraction_status, created_at, updated_at

paper_versions
  version_id, paper_id, source, source_identifier,
  version_label, published_at, url, license,
  is_preprint, is_canonical, metadata_json

artifacts
  artifact_id, paper_id, version_id, kind,
  path, sha256, mime_type, page_count, access_level,
  acquired_at, provenance_json

collections
  collection_id, name, description

paper_collections
  paper_id, collection_id

tags
  tag_id, name, prefix, description, active

paper_tags
  paper_id, tag_id, source, confidence, created_at

screening_events
  event_id, paper_id, decision, reason, actor, created_at
```

`111` 当前数据库继续保留每日快照语义，但它不是主库。新增 `sync_daily_inbox` 后，将每天的论文按规范主键幂等写入 `lab_kb.sqlite3`，并记录：

- `status:inbox`
- 日报日期和上游 `paper_id`
- 分类结果和关键词标签
- 摘要、作者、发布时间、DOI/arXiv ID
- 上游来源、同步批次和原始 JSON

同一论文连续多日出现时只更新发现记录，不重复创建论文。

### 2.2 PDF 与原文证据层

附件保存在内容寻址目录，不再按成员或临时脚本目录存放：

```text
data/library/
  objects/ab/cd/<sha256>.pdf
  objects/ef/01/<sha256>.md
  papers/<paper_id-safe>/
    metadata.json
    current.pdf -> ../../objects/...
    current.md  -> ../../objects/...
```

数据库保存真实路径、SHA-256、来源、许可和访问级别。重复文件只存一份。建议保留以下 `kind`：

- `pdf`
- `supplement`
- `fulltext_markdown`
- `code_archive`
- `dataset_reference`
- `annotation_export`

PDF 获取遵循以下顺序：已有合法本地文件、上游提供的附件、开放获取链接、人工上传。第一阶段不要自动绕过出版商权限下载 PDF。没有合法全文时，仍可保存元数据和摘要，但不得把摘要生成的内容标记为“全文证据”。

Markdown 转换必须尽量保留页码边界，至少输出类似标记：

```text
<!-- page: 12 -->
```

否则 MCP 无法可靠满足“定位到页码”的要求。当前已有转换 Markdown 可先迁移，但应把不能恢复页码的文档标为 `locator_quality=section_only`。

### 2.3 结构化阅读卡与证据层

不要再把知识卡只保存为一大段自由 Markdown。Markdown 作为人类可读视图，同时把关键字段写入数据库：

```text
reading_cards
  card_id, paper_id, template_version, reader,
  status, author_claims, lab_interpretation, lab_consensus,
  problem, contributions, methods, datasets,
  main_results, limitations, reproducibility,
  lab_relevance, reusable_assets, created_at, reviewed_at

evidence_spans
  evidence_id, paper_id, artifact_id, card_id,
  claim_type, quote_or_summary, page_start, page_end,
  section, figure, table_ref, source_offset_start,
  source_offset_end, provenance, created_at

paper_relations
  source_paper_id, target_paper_id, relation_type,
  note, evidence_id, created_at
```

必须明确区分：

- `author_claim`：作者原始主张。
- `reader_interpretation`：阅读者解释。
- `lab_consensus`：经过实验室复核的观点。
- `conflicting_evidence`：反例或冲突证据。

`test/extract_paper_library.py` 的提示词和并发 API 调用可复用，但需要改为：

1. 输入单个 `paper_id + artifact_id`，而不是解析固定格式的 `1.md`。
2. 返回严格 JSON Schema，再渲染为 Markdown。
3. 每条重要结论附 `page/section/figure/table` 定位。
4. 保存 `model`、提示词版本、输入文件 SHA-256、生成时间和审核状态。
5. 相同输入和提示词版本幂等，不重复付费生成。
6. 失败写入任务表，可重试，不再只写零散 `failures.json`。

建议阅读卡状态：

```text
draft_ai → pending_review → reviewed → superseded
```

AI 生成只能进入 `draft_ai`，不能直接成为实验室共识。

### 2.4 主题综述与决策层

使用 Git 友好的 Markdown 作为主题页载体：

```text
knowledge/topics/<topic-id>.md
knowledge/decisions/<decision-id>.md
knowledge/templates/reading-card.md
knowledge/vocabulary/tags.yaml
```

主题页 front matter 示例：

```yaml
---
id: cosmological-simulation
title: 宇宙学数值模拟
maintainer: lab
status: active
last_reviewed: 2026-08-05
paper_ids:
  - doi:10.1093/mnras/stt1789
---
```

主题页必须包含当前共识、支持证据、冲突证据、开放问题、项目影响和复核日期。后台索引器将主题页也转成 `knowledge_chunks`，但其来源类型标为 `topic_review`，避免和论文原文混淆。

## 3. 统一后台任务流水线

### 3.1 状态机

论文生命周期在数据库中统一为：

```text
inbox
  ├─ rejected
  ├─ screened
  │    ├─ queued_fulltext
  │    └─ metadata_only
  └─ core
       ↓
fulltext_ready
       ↓
card_draft
       ↓
pending_review
       ↓
reviewed
       ↓
indexed
```

状态和标签分开：状态表示流程位置，标签表示论文属性。不要同时用 `status` 字段和 `status:*` 标签表达不同事实；对外可把状态映射为同名展示标签。

### 3.2 任务表

用 SQLite 先实现可靠队列，5～50 人规模不必立即引入 Celery、Redis 或 Kafka：

```text
jobs
  job_id, job_type, paper_id, artifact_id,
  status, priority, attempts, max_attempts,
  available_at, locked_by, locked_at,
  input_hash, config_json, result_json,
  error, created_at, updated_at
```

任务类型：

- `enrich_metadata`
- `resolve_open_access`
- `acquire_fulltext`
- `convert_fulltext`
- `extract_reading_card`
- `generate_qa`
- `build_chunks`
- `refresh_index`
- `check_updates`
- `check_retraction`

一个常驻 worker 使用事务领取任务；每个任务必须具备幂等键 `job_type + paper_id + input_hash`。失败采用指数退避，超过最大次数进入 `dead_letter`，由 MCP 管理工具或 CLI 查看。

### 3.3 `111` 的改造

保留 `111` 的抓取、分类、每日摘要和历史日报查询，不在第一阶段重写。增加一个同步命令：

```bash
python3 -m literature_digest_agent.sync_lab_kb \
  --date 2026-08-04 \
  --target-db /srv/lab-kb/data/lab_kb.sqlite3
```

同步规则：

1. 从当日已发布快照读取论文。
2. 标准化 DOI、arXiv、标题和作者。
3. upsert `papers`、`paper_versions` 和 `discoveries`。
4. 把日报类别映射到受控标签，来源记为 `daily_classifier`。
5. 新论文设为 `inbox`；已有人工状态不得被同步覆盖。
6. 只把高优先级或人工选中的论文加入全文加工队列，避免每天自动处理全部 PDF。

`111` 的 SQLite 日报库继续承担“某天系统看到了什么”，统一主库承担“实验室长期保留什么”。

### 3.4 `test` 脚本的改造

将有价值逻辑迁入当前项目的新包，不把 `test` 作为生产运行目录：

```text
qa_knowledge_mcp/
  ingestion/
    identifiers.py
    daily_sync.py
    metadata.py
    artifacts.py
  processing/
    convert.py
    reading_card.py
    qa_generator.py
    worker.py
  storage/
    database.py
    migrations/
    repository.py
  indexing/
    chunks.py
    hybrid.py
```

迁移对应关系：

| `test` 原型 | 迁移目标 |
|---|---|
| `extract_paper_library.py` | `processing/reading_card.py` |
| `generate_cosmological_qa.py` | `processing/qa_generator.py` |
| `build_cosmological_core.py` | 一次性迁移命令 `migrate_legacy` |
| 旧 QA 索引构建脚本 | 合并进当前 `build_kb.py` |

生产代码不应依赖仓库外的绝对路径。历史数据统一保存在 `data/knowledge_acquisition`，只作为迁移输入和归档证据。

## 4. 检索与索引设计

### 4.1 检索单元

当前项目只检索 `question + answer`。新索引统一写入 `knowledge_chunks`：

```text
chunk_id, paper_id, artifact_id, source_type,
title, text, section, page_start, page_end,
tags_json, access_level, version_id,
content_hash, created_at, superseded_at
```

`source_type` 至少包括：

- `paper_fulltext`
- `paper_abstract`
- `evidence_span`
- `reading_card`
- `qa_pair`
- `topic_review`
- `decision_record`

QA 仍可作为高质量检索入口，但不再是唯一语料。搜索结果必须返回 `paper_id`、稳定标识、来源类型、版本、页码/章节、内容哈希和访问级别。

### 4.2 混合检索

沿用当前的 BM25/TF-IDF/embedding/reranker，并增加检索前过滤：

```text
权限、状态、年份、标签、collection、source_type 过滤
  → BM25 召回
  → 向量召回
  → 合并去重
  → rerank
  → 版本与撤稿降权
  → 返回证据
```

建议排序规则：

- `retraction_status=retracted` 默认警告并显著降权，但允许明确查询。
- `reviewed` 阅读卡高于 `draft_ai`。
- 正式出版版本和预印本关联为同一作品，默认不重复计数。
- 主题综述不能替代论文证据；回答重要事实时至少返回一个论文证据块。
- 没有页码的摘要或旧 Markdown 明确返回 `locator_quality`。

### 4.3 索引发布

不要让 MCP 在请求过程中重建全量索引。采用版本化目录和原子切换：

```text
data/indexes/build-20260805T120000Z/
data/indexes/current -> build-20260805T120000Z
```

后台任务构建完整新索引，通过校验后原子更新 `current` 软链接，再通知 MCP reload。失败时继续使用旧索引。

## 5. 统一 MCP 设计

第一阶段可以继续保留 `111:8000` 和知识库 `8001` 便于回滚；第二阶段把常用能力合并到当前 MCP，外部只配置一个地址。

### 5.1 只读工具

```text
search_papers(query, filters, limit)
get_paper(paper_id)
get_paper_evidence(paper_id, section, page)
search_knowledge(question, filters, top_k)
get_reading_card(paper_id)
list_topics()
get_topic(topic_id)
get_daily_digest(date, tags, limit)
get_sync_status()
knowledge_base_stats()
```

`search_knowledge` 返回候选证据，不伪装成已由模型验证的最终答案。若需要在 MCP 内生成回答，新增独立工具：

```text
answer_with_evidence(question, filters)
```

其输出结构固定包含：

```json
{
  "answer": "...",
  "confidence": "low|medium|high",
  "claims": [
    {
      "text": "...",
      "evidence_ids": ["..."],
      "stance": "paper_claim|lab_view|model_summary"
    }
  ],
  "papers": [
    {
      "paper_id": "doi:...",
      "doi": "...",
      "version_id": "...",
      "pages": [12]
    }
  ],
  "retrieved_at": "...",
  "index_version": "..."
}
```

### 5.2 写入与管理工具

写操作默认关闭，并使用独立管理令牌：

```text
import_paper(identifier_or_metadata, admin_token)
set_screening_status(paper_id, status, reason, actor, admin_token)
set_paper_tags(paper_id, tags, actor, admin_token)
enqueue_processing(paper_id, stages, admin_token)
review_reading_card(card_id, decision, actor, admin_token)
refresh_daily_catalog(date, admin_token)
rebuild_index(admin_token)
```

所有写操作写入 `audit_log`，记录操作者、工具名、参数摘要、前后状态和时间。MCP 不直接提供任意文件路径读取功能。

### 5.3 权限

单实验室第一版可使用三档访问级别：

- `public_metadata`：可暴露元数据和公开摘要。
- `lab`：实验室成员可访问阅读卡、主题页和获授权全文片段。
- `restricted`：仅特定项目或管理员可访问。

过滤必须发生在检索前。反向代理验证用户后，将可信身份/角色传给 MCP；如果当前 MCP SDK 无法安全接收身份上下文，则先部署两个端点或两个服务实例，分别使用不同数据库视图/索引，不能只在返回结果时删字段。

## 6. Linux 部署拓扑

推荐目录：

```text
/opt/lab-kb/app/              # 代码，只读发布
/srv/lab-kb/data/             # SQLite、索引、附件
/srv/lab-kb/knowledge/        # 主题页和决策 Markdown
/srv/lab-kb/backups/          # 备份
/etc/lab-kb/lab-kb.env        # 密钥和配置，chmod 600
/var/log/lab-kb/              # 日志
```

建议进程：

| 进程 | 作用 | 启动方式 |
|---|---|---|
| `lab-kb-mcp.service` | 统一 Streamable HTTP MCP | systemd 常驻 |
| `lab-kb-worker.service` | 转换、抽取、QA、索引任务 | systemd 常驻 |
| `literature-daily.service` | 拉取 `111` 每日快照 | systemd oneshot |
| `literature-daily.timer` | 每日触发 | systemd timer |
| `lab-kb-maintenance.timer` | 更新检查、备份、清理 | systemd timer |
| Nginx/Caddy | TLS、认证、限流 | systemd 常驻 |

不要直接将 `0.0.0.0:8001` 暴露到公网。MCP 服务监听 `127.0.0.1:8001`，由反向代理提供 HTTPS。至少设置：请求体限制、超时、访问日志、令牌认证、来源限制和速率限制。

SQLite 初期配置 WAL 模式和 `busy_timeout`。数据库、worker 和 MCP 最好位于同一台机器；若以后多机写入或并发明显增加，再迁移 PostgreSQL。附件目录可继续使用本地磁盘，容量增长后切换 MinIO/S3 兼容对象存储。

### 6.1 建议环境变量

```bash
LAB_KB_DATABASE=/srv/lab-kb/data/lab_kb.sqlite3
LAB_KB_LIBRARY_ROOT=/srv/lab-kb/data/library
LAB_KB_KNOWLEDGE_ROOT=/srv/lab-kb/knowledge
LAB_KB_INDEX_ROOT=/srv/lab-kb/data/indexes
LAB_KB_MCP_HOST=127.0.0.1
LAB_KB_MCP_PORT=8001
LAB_KB_ADMIN_TOKEN=change-me
LAB_KB_TIMEZONE=Asia/Shanghai
LAB_KB_EMBEDDING_MODEL=/opt/models/bge-small-zh-v1.5
LAB_KB_ENABLE_RERANKER=false
LAB_KB_LLM_BASE_URL=https://example/v1
LAB_KB_LLM_API_KEY=...
LAB_KB_LLM_MODEL=...
```

密钥不能写入仓库、Markdown 卡片、任务输入或 MCP 返回值。

## 7. 现有数据迁移

当前宇宙学知识库可作为第一个正式 collection，无需重新生成后再上线。

### 7.1 迁移顺序

1. 创建新数据库和 schema migration 机制。
2. 读取 `data/cosmological_simulation/core_papers.json` 建立 90 篇论文元数据。
3. 为每篇论文生成规范 `paper_id`，记录旧 hash/文件名到 `external_ids`。
4. 导入 `data/knowledge_acquisition/paper_library_1_knowledge/papers/*.knowledge.md` 为 `reading_card` 或 `legacy_knowledge_note`。
5. 导入 `data/cosmological_simulation/generate_paper.jsonl` 的 2402 条 QA，关联到论文，而不是只保留旧 `doc_id`。
6. 对能定位的原始 Markdown 建立 `artifact`；计算 SHA-256，记录是否具备页码。
7. 为 90 篇论文打上 `topic:cosmological-simulation` 和 collection。
8. 构建新版本索引，与现有索引做回归查询对比。
9. 校验通过后切换统一 MCP；旧服务保留一周只读回滚窗口。

### 7.2 迁移校验

迁移程序输出机器可读报告：

```text
paper_total
paper_with_stable_id
paper_without_stable_id
duplicate_groups
artifact_total
orphan_artifacts
reading_card_total
qa_total
qa_without_paper
locator_page_count
locator_section_only_count
```

最低要求：90 篇论文和 2402 条 QA 数量一致，`qa_without_paper=0`，旧查询 Top-5 召回覆盖率不低于 95%。

## 8. 分阶段执行计划

### 阶段 0：冻结规则与备份，1～2 天

- 确定负责人、管理员和主题维护人。
- 固定受控标签词表、阅读卡模板和论文状态。
- 备份三个目录中的 SQLite、JSONL、Markdown 和附件。
- 确认服务器磁盘、备份位置、域名、TLS 和模型/API 条件。

验收：规则文件进入仓库，备份可解压，抽查 5 个文件 SHA-256 一致。

### 阶段 1：统一事实库，3～5 天

- 在当前项目增加 SQLite schema、repository 和 migration CLI。
- 实现 DOI/arXiv/标题规范主键和跨来源去重。
- 实现 `111 → lab_kb.sqlite3` 的幂等 Inbox 同步。
- MCP 增加 `search_papers`、`get_paper`、`get_daily_digest`。

验收：同一 DOI 多次同步只有一篇论文；人工状态和标签不会被日报覆盖；无 DOI 论文可稳定重复识别。

### 阶段 2：迁移历史知识，3～5 天

- 导入现有 90 篇核心论文和 2402 条 QA。
- 导入知识 Markdown 和原始转换文件。
- 为每个结果补齐 `paper_id`、来源类型、版本和定位质量。
- 建立迁移报告与回归查询集。

验收：数量一致、无孤立 QA、典型问题可返回稳定标识和来源。

### 阶段 3：后台加工流水线，5～8 天

- 将 `test` 的抽取与 QA 逻辑迁成可重试任务。
- 实现附件入库、哈希去重、全文转换和结构化阅读卡。
- 实现人工审核状态，不允许 AI 卡片自动进入 `reviewed`。
- 实现 worker 健康检查、失败查询和重试 CLI/MCP。

验收：选择 5 篇新论文完整跑通；重复执行不重复调用模型；人为制造失败后可恢复。

### 阶段 4：统一检索与 MCP，4～7 天

- 扩展索引到全文、证据、阅读卡、QA 和主题页。
- 增加 metadata/tag/status/access 预过滤。
- 实现版本化索引和原子发布。
- 增加带证据回答协议，保存索引版本和检索时间。

验收：重要结论能返回 DOI/arXiv 和页码/章节；撤稿、预印本和权限规则生效；无证据问题明确返回不足。

### 阶段 5：Linux 生产部署，2～4 天

- 创建专用 Linux 用户和目录权限。
- 配置 systemd service/timer、日志轮转和反向代理。
- 配置每日数据库备份、每周附件增量备份、每季度恢复演练。
- 运行 7 天观察期，保留旧 MCP 只读回滚。

验收：服务器重启后自动恢复；任务不会重复消费；从备份可在空目录恢复数据库、主题页和至少一篇附件。

整体工程实现预计 3～5 周；实验室流程形成稳定习惯仍建议按 6～8 周观察和调整。

## 9. 日常运行制度

### 每日

1. `111` 拉取并发布昨日窗口的论文快照。
2. 同步到统一 Inbox。
3. 自动补全元数据和去重。
4. 只对命中核心规则的论文排队，其他等待人工筛选。
5. worker 加工已批准论文并增量发布索引。

### 每周

- 组会处理 Inbox 和 `pending_review` 阅读卡。
- 更新至少一个主题页，而不只汇报单篇论文。
- 检查失败任务、孤立附件和无稳定标识论文。

### 每月

- 合并重复论文和失控标签。
- 检查核心论文版本、更正与撤稿状态。
- 导出 `papers.jsonl`、`reading_cards.jsonl`、主题 Markdown 和索引 manifest。

### 每季度

- 在独立临时目录执行一次恢复测试。
- 复核管理员、MCP 令牌和备份保留策略。
- 抽检 AI 阅读卡，评估无出处主张和错误定位比例。

## 10. 测试与验收指标

### 单元测试

- DOI/arXiv/标题规范化和去重。
- 状态转换合法性。
- 同步幂等和人工字段保护。
- 任务领取、锁超时、重试和死信。
- 权限过滤先于召回。
- 预印本/出版版本归并。

### 集成测试

- 模拟一份 `111` 日报，完成同步、筛选、附件、卡片、QA、索引和 MCP 查询。
- 索引构建失败时旧索引继续可用。
- MCP 重启和 worker 重启后不丢任务。
- 备份恢复后所有外键、文件哈希和主题链接有效。

### 业务指标

- 稳定标识完整率超过 95%。
- 核心论文阅读卡覆盖率达到 100%。
- 裸 PDF 比例接近 0。
- 重要判断两分钟内可定位原始出处。
- `pending_review` 中位等待时间小于 7 天。
- 每日同步成功率超过 99%，失败可追踪。
- 重要问答的证据引用覆盖率达到 100%。
- 新成员一周内可通过主题页理解一个方向的关键脉络。

## 11. 第一批开发任务清单

按依赖顺序建议创建以下任务：

1. `storage`: schema、migration、repository、事务和备份命令。
2. `identifiers`: DOI/arXiv/PMID/标题规范化与合并策略。
3. `legacy-migration`: 90 篇论文、知识卡和 2402 条 QA 导入。
4. `daily-sync`: 从 `111` SQLite 或其 repository 同步 Inbox。
5. `artifacts`: 内容寻址文件库、哈希、合法来源和访问级别。
6. `jobs`: SQLite 队列、worker、重试、死信和幂等。
7. `reading-card`: 严格 JSON Schema、Markdown 渲染、审核流程。
8. `chunks`: 多来源 chunk schema 和页码定位。
9. `index-release`: 版本化构建、校验、原子切换和 reload。
10. `mcp-v2`: 统一只读工具、受控写工具、审计和权限。
11. `ops`: systemd、反向代理、日志、备份和恢复脚本。
12. `evaluation`: 固定查询集、召回回归和出处完整率报告。

## 12. 暂不实施的内容

以下能力有价值，但不应阻塞第一版：

- 不立即部署知识图谱数据库；先用关系表表达引用和论文关系。
- 不立即将全部每日论文全文向量化；先筛选再加工。
- 不把 Google Scholar 抓取作为核心链路。
- 不让模型自动修改人工标签、共识或项目决策。
- 不在第一阶段实现复杂多人 ACL；先用清晰的三档访问级别。
- 不立即替换 `111` 的稳定日报能力；先通过同步边界解耦。
- 不立即引入 PostgreSQL、Redis、Celery、MinIO；达到实际容量或并发阈值后再迁移。

完成以上阶段后，系统将形成清晰闭环：`111` 负责发现，统一 SQLite 负责论文事实与流程状态，文件库负责原文证据，结构化卡片和主题 Markdown 负责实验室理解，当前项目负责混合检索与统一 MCP。这样既复用了现有成果，也避免继续让临时 JSONL、脚本输出目录和多个 MCP 各自成为事实源。
