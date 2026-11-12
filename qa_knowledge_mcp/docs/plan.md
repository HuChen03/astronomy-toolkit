# 当前项目知识库优化方案

> 制定日期：2026-08-07  
> 依据：`docs/survey.md`、当前项目文档、实现代码、测试和现有宇宙学 QA 数据。  
> 目标：在不推翻现有 MCP 服务的前提下，把当前“单主题 JSONL QA 检索”逐步升级为可追溯、可版本化、可增量维护、可评估的实验室知识库。

---

## 1. 结论摘要

当前项目已经完成一个可用的知识检索原型：统一 MCP 同时提供每日论文发现和 QA Evidence Pack；90 篇宇宙学数值模拟论文已形成 2402 条 QA；BM25、TF-IDF、可选向量召回和轻量重排能够支持基础问答检索。

### 1.1 实施状态（2026-08-10）

本轮已将方案中的第一批基础能力落到代码和数据中：

- 已完成 SQLite 知识覆盖层：论文、QA family/version、Evidence、taxonomy、索引版本和增量任务表。
- 已迁移 90 篇论文、2402 条 QA 和 2402 条 Evidence；当前真实中台匹配结果为 86 篇 `matched`、3 篇 `needs_review`、1 篇 `legacy_unmatched`，未伪造文献中台 ID。
- 已完成章节/正文段落级的保守证据对齐；无法确认时保留 `qa_pair`，不生成虚假页码。
- 已完成不可变索引发布、active 指针、QA/Evidence/知识文档覆盖层快照、检索评测和 RRF 统一检索；当前 active index 为 `20260811T091518Z-f12c2aae0506`。
- 已接入阅读卡/主题/决策 Markdown 的通用导入器，并纳入统一文档检索；新增结构化 `reading_cards`、`topics`、`decisions` 表，现有 11 篇历史知识卡已转换为 `draft_ai`，其中 7 篇绑定论文。Topic/Decision 当前提供模板和完整导入/query 能力，不伪造实验室共识或决策。
- 已提供 `search_lab_knowledge`、`answer_with_evidence`、任务入队/查看和覆盖层统计 MCP 工具。
- 已接入文献中台 `/api/v1/read` 和 `/api/v1/search/offline` 客户端；新增 DOI/标题匹配、人工复核队列和 `qa-knowledge-worker` 任务执行入口。
- 已将 `answer_with_evidence` 默认限制为 `reviewed`、`approved` 或 `verified` QA，避免未审核内容直接成为回答。
- 已接入中台 Markdown Backfill dry-run；由于中台按共享盘路径读取，命令支持 `--remote-dir`，不会把当前项目不可见的本地路径误提交。
- 已接入引用/被引关系表和中台同步命令 `qa-knowledge-sync-relations`；接口返回空列表时正常记录为 0，瞬时超时可安全重试。
- 当前验证结果：`pytest -q` 为 `41 passed`；BM25 离线评测集为 10 cases、Recall@10 1.0、MRR 0.8333、nDCG@10 0.8762。

真实中台地址必须通过 `LITERATURE_HUB_BASE_URL` 显式配置，不再假定本机端口。配置后可运行 `qa-knowledge-worker` 或 `python -m pipelines.knowledge_acquisition.match_hub_papers`。仍需外部系统或人工流程完成的部分：Evidence 页码/图表解析、阅读卡审核、权限审计和生产部署。

下一阶段不应优先增加更大的模型、知识图谱或自动回答，而应先解决以下基础问题：

1. **论文身份不统一**：当前以 QA 文档 hash 和历史 `paper_key` 为主，尚未稳定绑定文献中台 UUID。
2. **证据定位不足**：证据只能回到 JSONL 行号和 QA 序号，无法核验 PDF 页码、章节、图表或原文片段。
3. **QA 不是完整知识实体**：缺少版本、审核状态、质量、来源流水线、失效关系和证据关联。
4. **知识类型混杂**：论文原始主张、模型摘要、阅读者解释、实验室共识和冲突证据没有严格区分。
5. **数据更新仍是全量文件流程**：没有增量任务、幂等重跑、原子发布、回滚和索引版本治理。
6. **检索缺少评测闭环**：现有加权分数固定，尚无回归问题集、Recall、MRR、nDCG、证据命中率等指标支撑调参。
7. **工程边界尚未完全收敛**：调研文档提出独立 PostgreSQL 主库，但当前项目已经依赖文献中台作为论文事实源；两者需要按现状重新分工，避免重复建设论文元数据、附件和引用关系。

推荐路线是：

```text
文献中台：论文事实、附件、全文、引用关系
        |
        | hub_paper_id / DOI / arXiv ID
        v
实验室知识覆盖层：筛选状态、阅读卡、QA、Evidence、主题、决策、审核
        |
        v
版本化混合检索：QA + 阅读卡 + Evidence + 主题页 + 可选原文 Chunk
        |
        v
统一 MCP：论文发现、知识检索、证据读取、处理状态
```

近期采用 SQLite 或兼容的关系存储建立知识覆盖层即可；当数据规模、并发、权限或多 worker 一致性出现明确需求时，再迁移到 PostgreSQL + pgvector。OpenSearch、专用向量数据库和 Neo4j 暂不进入近期实施范围。

---

## 2. 当前项目基线

### 2.1 已有能力

- 单一 `lab-knowledge` MCP 服务，支持 stdio 和 Streamable HTTP。
- `list_knowledge_bases`：列出主知识库和已启用的小方向知识库。
- `search_knowledge`：默认检索主库，指定小方向时检索主库加方向库，并返回 QA Pair 及原文段落。
- BM25、TF-IDF、可选 SentenceTransformer + FAISS、可选 CrossEncoder。
- embedding 或 reranker 不可用时自动降级。
- 离线生成 `chunks.jsonl` 和 `manifest.json`。
- 日报磁盘缓存和文献中台不可用时的结构化降级。
- Topic、Decision、独立 Evidence 和日报工具暂保留为内部迁移资产，不注册为当前 MCP 工具。

### 2.2 当前数据事实

| 项目 | 当前值 |
|---|---:|
| 论文 | 90 篇 |
| QA | 2402 条 |
| 主题 | 宇宙学数值模拟 |
| 受控类别 | 6 类 |
| 向量索引 | 当前 manifest 中未启用 |
| QA 状态 | 原始数据中未记录 |
| 证据定位 | JSONL `source_line + pair_id` |

六个现有类别是：

- 旗舰模拟与项目：20 篇。
- 代表性科学应用：20 篇。
- 经典代码与数值方法：18 篇。
- 快速模拟与模拟器：16 篇。
- 综述与数值可靠性：8 篇。
- 数据资源与 Mock：8 篇。

这些类别可以作为初始 Research Direction 候选，但不应继续只保存在单个字符串字段中，也不应被当作物理目录或 namespace。

### 2.3 当前实现中的关键限制

#### 数据模型

- 一篇论文和全部 QA 被打包在同一行 JSON 中。
- `pair_id` 依赖数组位置；重新生成或调整顺序后不稳定。
- `doc_id` 实际是历史知识记录 hash，不等同于 canonical Paper ID。
- QA 缺少独立 ID、版本、状态、审核人、生成配置和 evidence link。
- `source_file` 和历史 `paper_source` 含本地路径语义，存在迁移和泄露风险。

#### 检索

- 只检索 QA，没有 Paper Analysis、阅读卡、原文 Chunk、主题综述等检索目标。
- BM25、TF-IDF、dense、rerank 采用固定原始分数归一化加权，缺少基于评测的校准。
- 当前结果虽然按论文限流，但没有重复 QA 去重、来源类型路由、审核状态和证据质量加权。
- 没有研究方向、时间、论文、来源类型、审核状态、访问级别等结构化预过滤。
- manifest 只校验记录数量，不能充分判断源文件、chunker、模型或配置是否匹配。

#### 更新与运维

- 更新依赖修改原 JSONL、全量构建、手动 reload。
- 没有任务状态、失败重试、死信、幂等键和发布审核。
- 索引目录没有明确的不可变版本和 active pointer，难以原子切换与回滚。
- 缺少数据质量报告、索引一致性检查和定期备份恢复验证。

#### 测试与评估

- 已有测试覆盖基础加载、检索、Evidence Pack、日报和 MCP 注册。
- 当前已通过 `pyproject.toml` 固化 `src` 布局和测试入口，直接执行 `pytest -q` 可完成收集与运行。
- 测试主要验证功能是否可调用，没有真实语料检索质量回归集。

---

## 3. 优化目标与原则

### 3.1 优化目标

#### 近期目标

在保留现有服务可用性的同时，完成历史数据治理和可追溯升级：

- 90 篇论文全部绑定稳定的文献中台 ID 或明确的待匹配状态。
- 2402 条 QA 全部迁移为独立、稳定、可版本化的知识实体。
- 重要 QA 能定位到原文页码、章节或至少可验证文本片段。
- 搜索结果明确区分 QA、论文证据、阅读卡和实验室观点。
- 新论文能够通过任务流水线增量进入知识库，而不是手工修改主 JSONL。
- 每次知识索引发布都可验证、可切换、可回滚。

#### 中期目标

- 支持 Paper Analysis、结构化阅读卡、主题综述和决策记录。
- 建立 QA、Analysis、Evidence、Chunk 的统一混合检索。
- 支持研究方向、标签、论文、年份、审核状态和访问级别过滤。
- 建立离线检索评测、线上查询日志和失败案例复盘机制。
- 已提供受约束的 `answer_with_evidence` 初版：仅返回带可定位 Evidence 的已检索 QA，不进行无依据生成。

#### 长期目标

- 支持几万至几十万篇论文和数百万级知识 Chunk。
- 支持跨论文综合、引用关系检索、主题演化和研究决策辅助。
- 仅在真实评测与压测证明必要时引入 PostgreSQL + pgvector、OpenSearch、专用向量数据库或图数据库。

### 3.2 设计原则

1. **文献中台是论文事实源**：论文 metadata、PDF、Markdown、引用与被引关系不在本项目重复维护主副本。
2. **本项目是实验室知识覆盖层**：只维护实验室工作流和派生知识，包括 QA、阅读卡、证据、主题和决策。
3. **原始输入不可变**：历史 JSONL、模型输出和 parser 产物作为 import artifact 保存，不直接充当长期在线模型。
4. **派生知识必须版本化**：QA、Analysis、Evidence alignment、ChunkSet 和 embedding 都要记录版本与 provenance。
5. **任何重要结论都可回到证据**：至少返回论文稳定 ID、证据文本和定位质量；无法定位时明确降权和提示。
6. **分类与策展分离**：Research Direction、Topic、Tag、Collection、Namespace 各司其职。
7. **检索索引可重建**：关系数据和 artifact 是事实，BM25、向量和图索引都是可删除重建的派生物。
8. **先评测再扩基础设施**：不以“可能更先进”为理由提前引入复杂组件。
9. **兼容迁移优先**：现有 MCP 工具在迁移期保留，通过内部适配转向新检索层。

---

## 4. 目标架构

### 4.1 责任边界

#### 文献中台负责

- canonical Paper ID 和元数据。
- DOI、arXiv ID 等外部标识。
- PDF、Markdown 和 parser 任务状态。
- 作者、期刊、年份、摘要。
- references、citations 和 related paper。
- 每日论文发现和在线检索。

#### 当前项目负责

- 实验室收录、筛选、优先级、负责人和阅读状态。
- Research Direction、Topic、Tag、Collection 的实验室侧分配。
- 外部生成 QA 的导入、版本、审核、失效与去重。
- 结构化阅读卡和 Paper Analysis。
- Evidence 与中台全文位置的关联。
- 主题综述、实验室共识、冲突证据和决策记录。
- 面向 Agent 的统一知识检索和 Evidence Bundle。

### 4.2 逻辑分层

```text
Layer 1  Paper Fact
  Hub Paper / metadata / artifact / citation

Layer 2  Source Evidence
  DocumentVersion / Section / Chunk / page-span / figure / table

Layer 3  Derived Paper Knowledge
  QA / PaperAnalysis / ReadingCard / evidence links / review status

Layer 4  Lab Synthesis
  Topic summary / consensus / conflicting evidence / decision record

Layer 5  Retrieval and Access
  filters / BM25 / dense / fusion / rerank / MCP / audit
```

### 4.3 存储策略

#### 第一阶段

- 使用 SQLite 保存实验室覆盖层关系数据，便于快速落地、迁移和备份。
- 历史 JSONL 保留为只读 import artifact。
- Markdown、解析 JSON 和索引版本继续使用文件系统，但通过统一 artifact locator 访问。
- 检索仍可使用本地 BM25、TF-IDF 和 FAISS，先完成接口与版本治理。

#### 迁移到 PostgreSQL + pgvector 的触发条件

满足以下任意多项时再迁移：

- 论文和知识记录进入十万级，单机全量索引耗时影响日常发布。
- 多个 worker 或管理员并发写入，SQLite 锁竞争明显。
- 需要事务内同时更新实体、权限、版本和向量状态。
- 需要复杂多条件过滤、审计查询和稳定分页。
- 需要行级权限、多个真实 namespace 或高可用部署。
- 压测证明本地 FAISS 加载、内存或发布方式成为瓶颈。

#### 暂缓组件

- OpenSearch：直到 PostgreSQL FTS 或现有 lexical 检索无法满足召回、过滤或吞吐。
- Qdrant、Milvus、Weaviate：直到 pgvector 或本地 FAISS 有可复现的性能瓶颈。
- Neo4j：直到多跳引用、实体关系或图算法成为高频且可量化的需求。
- 自动知识图谱和 cross-paper QA：直到证据、实体消歧和审核机制稳定。

---

## 5. 核心数据优化

### 5.1 论文身份映射

建立独立的论文映射层，不再让 `doc_id` 同时承担论文 ID 和 QA 文档 ID：

```text
hub_paper_id
doi
arxiv_id
legacy_paper_key
legacy_doc_hash
match_method
match_confidence
match_status
matched_at
reviewed_by
```

匹配优先级：

1. DOI 精确匹配。
2. arXiv ID + version。
3. 其他外部稳定 ID。
4. 标题、作者、年份的规范化匹配。
5. PDF 或 Markdown 内容 hash。
6. 人工确认。

验收要求：90 篇论文没有静默误匹配；无法确认的记录进入 `needs_review`，不能强行合并。

### 5.2 QA 一等实体化

将当前数组中的 QA 拆成逻辑 QA 和 QA Version：

```text
LogicalQA
  qa_id
  hub_paper_id
  canonical_question
  lifecycle_status

QAVersion
  qa_version_id
  qa_id
  question
  answer
  source_pipeline
  source_run_id
  prompt_or_config_version
  created_at
  review_status
  quality_score
  supersedes_version_id
  content_hash
```

建议生命周期：

- `imported`
- `needs_review`
- `validated`
- `active`
- `superseded`
- `deprecated`
- `rejected`

默认检索只包含满足访问权限的 `active` 版本；历史版本保留用于审计和回滚。

### 5.3 Evidence 模型

QA 和阅读卡结论通过 Evidence 关联原文，而不是把 answer 本身视为原文：

```text
evidence_id
hub_paper_id
document_version_id
evidence_text
page_start/page_end
section_path
figure_ref/table_ref/equation_ref
char_start/char_end
normalized_block_anchor
locator_quality
alignment_method
alignment_confidence
review_status
source_sha256
```

定位质量建议分级：

- `exact_span`：可回到稳定字符区间。
- `page`：页码可靠，但字符位置不稳定。
- `section`：只有章节定位。
- `text_match`：能匹配文本，但 parser 位置不完整。
- `qa_pair`：只能回到历史 QA。
- `unverified`：无可靠原文证据。

检索排序和回答置信度应使用该等级，而不是隐藏证据质量差异。

### 5.4 知识类型

所有知识记录增加明确的 `knowledge_type` 或 `stance`：

- `paper_claim`：论文作者明确主张。
- `paper_result`：论文实验或模拟结果。
- `model_summary`：模型生成的概括。
- `reader_interpretation`：阅读者解释。
- `lab_consensus`：经过审核的实验室共识。
- `conflicting_evidence`：与已有观点冲突或形成边界条件的证据。
- `decision_record`：实验室技术或研究决策。

AI 自动产物只能先进入 `model_summary + needs_review`，不得直接成为 `lab_consensus`。

### 5.5 分类体系

将当前单值 `paper_category` 升级为多层次、多标签结构：

- **Research Direction**：稳定、层级化、人工维护，可有 primary 和 secondary。
- **Topic**：随语料和研究活动演化的主题，可合并和重算。
- **Tag**：细粒度扁平标签，如代码、数据集、物理过程、数值方法。
- **Collection**：人工策展集合，如“新成员必读”“项目 A 复现清单”。
- **Namespace**：只用于真实权限、生命周期或资源边界。

现有六类先作为 taxonomy v1 的一级或二级候选节点导入，并保留原始分类 provenance。后续调整通过 taxonomy version、deprecated 和 successor 关系完成，不覆盖历史记录。

---

## 6. 检索优化方案

### 6.1 多目标检索

统一检索层至少支持：

| 检索目标 | 适用问题 | 主要返回 |
|---|---|---|
| Paper | 找论文、作者、年份、方向 | 中台论文 ID 和摘要 |
| QA | 与已有问题高度相似 | 已审核答案和 evidence |
| Reading Card / Analysis | 方法、贡献、限制、数据集 | 结构化字段和 evidence |
| Evidence / Chunk | 数值、公式、定义、原文核验 | 原文片段和位置 |
| Topic / Decision | 实验室共识和项目判断 | 明确标注为实验室知识 |
| Citation | 上下游工作和研究脉络 | 关系类型和论文信息 |

### 6.2 查询流程

```text
Query understanding
  → 访问级别、论文、方向、时间、知识类型过滤
  → QA / Analysis / Evidence / Paper 并行召回
  → 各检索器内部归一化
  → RRF 融合
  → reranker
  → 重复内容消除和论文多样性控制
  → evidence 质量、审核状态、时效性加权
  → Evidence Bundle
```

不再长期依赖 BM25、TF-IDF、dense 原始分数的固定线性相加。近期可保留现有实现作为 baseline，同时增加 RRF 实现并用评测集比较。

### 6.3 索引文档表示

至少建立以下检索表示：

- QA question-only。
- QA question + concise answer。
- 阅读卡字段级文档，而不是整卡拼成一个超长文本。
- Evidence 原文片段 + section heading + paper title。
- Topic 和 Decision Markdown 的章节级 chunk。
- 可选正文 Chunk，默认只在 QA 和 Analysis 不足时使用。

每个索引文档统一包含：

```text
retrieval_doc_id
source_type
source_entity_id
hub_paper_id
text
direction_ids/topic_ids/tag_ids
review_status
access_level
locator_quality
content_hash
source_version
index_version
embedding_version
```

### 6.4 结构化过滤

在召回前应用：

- 访问级别和 namespace。
- active / reviewed 状态。
- Paper ID、Research Direction、Topic、Tag、Collection。
- 年份、作者、venue。
- source type。
- locator quality 和最低质量分。
- 是否有全文、是否有已审核 evidence。

这部分对检索质量和安全性的价值高于盲目扩大向量 top-k。

### 6.5 Evidence Bundle 标准

所有知识搜索统一返回：

```text
query
retrieval_plan
index_version
matched
items[]
  source_type
  source_entity_id
  hub_paper_id
  title / DOI / arXiv ID
  text
  score / rank signals
  knowledge_type
  review_status
  evidence_ids
  page / section / figure / table
  locator_quality
provenance
```

对外返回不得包含服务器绝对路径、内部任务路径、密钥或未授权全文位置。

---

## 7. 增量加工与索引发布

### 7.1 任务流水线

```text
discover or import
  → resolve paper identity
  → acquire/read full text from hub
  → normalize document
  → align legacy QA evidence
  → import/generate reading card and QA
  → validate
  → build retrieval documents
  → build candidate index version
  → run data and retrieval checks
  → publish active index
```

每个任务记录：

- stage、status、attempt、priority。
- 输入 artifact hash、上游 version 和配置 version。
- started_at、finished_at、worker、错误类型。
- retry_after、dead_letter_reason。
- 输出 entity/version/artifact ID。

### 7.2 幂等策略

幂等键至少包含：

```text
hub_paper_id
document_version
stage
input_content_hash
pipeline_config_version
prompt_version 或 parser/chunker/model version
```

相同输入重复执行应复用已有输出；配置或上游版本变化时生成新版本，不覆盖旧版本。

### 7.3 索引版本

索引目录建议改为：

```text
data/indexes/
  versions/<index_version>/
    documents.jsonl
    lexical/
    vectors/
    manifest.json
    validation.json
  active.json
```

`manifest.json` 至少包含：

- index schema version。
- source snapshot/version。
- 各 source type 数量。
- source hash 集合或数据库 checkpoint。
- chunker、tokenizer、embedding、reranker 版本。
- 构建时间和构建程序版本。
- 维度、距离函数和归一化方式。

发布流程：构建不可变候选版本，完成校验后原子更新 `active.json`；reload 只读取 active 版本；出现回归时切回上一版本。

---

## 8. MCP 优化

### 8.1 当前 MCP 工具边界

当前仅注册两个只读工具：`list_knowledge_bases` 和 `search_knowledge`。
检索结果以 QA Pair 和 `source_paragraph` 为核心；不提供写入、审核、重载、日报同步或自动回答。
旧工具代码可在内部迁移期间保留，但不得重新注册到 MCP。

### 8.2 暂不新增其他工具

文献中台、论文详情、Evidence 管理和知识库管理工具暂不对外提供，待核心 QA 检索稳定并完成评测后再单独设计。

后续新增工具应经过独立的接口评审，不直接恢复历史工具列表。

### 8.3 带证据回答

后续若扩展 `answer_with_evidence`，仍必须满足以下条件：

- 检索评测达到设定门槛。
- 重要 QA 的 evidence 覆盖达到目标。
- knowledge type 和 review status 已生效。
- 回答能够逐 claim 绑定 evidence。
- 无证据时能够稳定拒答。

---

## 9. 分阶段实施计划

### 阶段 0：基线固化与工程修复，1～2 天

任务：

- 固化 90 篇、2402 条 QA 的数据快照和校验报告。
- 标准化开发安装和测试命令，修复测试收集时的包导入问题。
- 为当前检索准备 30～50 个代表性回归问题，记录 baseline top-k。
- 补充数据检查 CLI：缺字段、重复 key、空 QA、非法 DOI、数量漂移。
- 确认文献中台 ID、全文读取和任务状态接口契约。

验收：

- 本地一条命令可运行全部测试。
- 历史数据数量和 hash 可重复验证。
- 回归集能输出当前 BM25/TF-IDF baseline。

### 阶段 1：论文身份与覆盖层，3～5 天

任务：

- 增加 typed hub client、超时、重试、字段清洗和错误分类。
- 建立实验室覆盖层数据库和 migration。
- 建立 legacy hash/key 到 `hub_paper_id` 的映射及人工复核队列。
- 保存实验室收录状态、优先级、标签、负责人和审计记录。
- MCP 增加 `search_library`、`get_paper` 和覆盖层状态查询。

验收：

- 90 篇论文全部完成匹配或进入明确的 `needs_review`。
- 同一中台 UUID 重复导入不会产生重复论文记录。
- MCP 返回不泄露中台和本机绝对路径。

### 阶段 2：QA 实体化与证据对齐，5～8 天

任务：

- 将 2402 条历史 QA 导入 LogicalQA、QAVersion 和 import provenance。
- 生成稳定 QA ID，不再把数组序号作为长期身份。
- 从中台 Markdown 恢复章节、页码标记和原文候选片段。
- 实现 exact/lexical/fuzzy evidence alignment 和人工复核状态。
- Evidence Pack 返回中台论文 ID、QA version、locator 和 alignment 信息。

验收：

- 2402 条 QA 无孤立记录、数量无丢失。
- 所有 QA 有明确 lifecycle 和 review status。
- 核心高频 QA 的页码或章节证据覆盖率达到 80% 以上。
- 无法定位的 QA 明确标记为 `unverified`，不伪造页码。

### 阶段 3：结构化阅读卡与知识类型，5～8 天

任务：

- 定义阅读卡 schema：问题、贡献、方法、假设、数据、结果、局限、可复现性和实验室关联。
- 将阅读卡字段拆成可独立检索、独立引用的 analysis fragment。
- 增加 `paper_claim`、`model_summary`、`reader_interpretation`、`lab_consensus` 等类型。
- 建立 draft、reviewed、rejected、superseded 流程。
- 选取 5～10 篇代表性论文跑通完整加工与审核。

验收：

- AI 内容不会自动成为实验室共识。
- 每个重要阅读卡结论至少绑定一个 Evidence，或明确标记无证据。
- 重复加工同一输入不会产生重复 active 版本。

### 阶段 4：统一检索与评测，5～7 天

任务：

- 抽象统一 retrieval document 和 retriever adapter。
- 支持 QA、Analysis、Evidence、Topic 多来源召回。
- 增加结构化过滤、RRF、reranker、去重和论文多样性控制。
- 建立 immutable index version、校验和 active pointer。
- 扩展评测集并输出 Recall@k、MRR、nDCG、Evidence Hit Rate 和 Paper Diversity。

验收：

- `search_lab_knowledge` 能标明每条结果的来源类型。
- 新检索在回归集上优于或不低于当前 baseline。
- 索引可原子发布并在一次操作内回滚。
- 关闭 embedding 时仍有可用且可评测的 lexical 路径。

### 阶段 5：主题综述与日常闭环，4～7 天

任务：

- 建立 `knowledge/topics/` 和 `knowledge/decisions/`。
- 主题页显式记录支持证据、冲突证据、适用边界和最近复核时间。
- 每日论文候选幂等进入 Inbox，不覆盖人工状态。
- 建立周度审核、月度 taxonomy 和索引健康检查流程。
- 将主题页和决策记录纳入检索，但明确标注为实验室观点。

验收：

- 至少形成 3 个宇宙学数值模拟主题页。
- 每个实验室共识都能回到论文 Evidence。
- 重复执行日报和同步不会覆盖人工筛选字段。

### 阶段 6：生产化与受约束回答，3～5 天

任务：

- 增加认证、访问级别过滤、审计、日志轮转和健康检查。
- 建立数据库、artifact、主题 Markdown 和索引的备份恢复流程。
- 增加任务重试、死信查询、监控指标和告警。
- 将当前 QA 级回答扩展为逐 claim 引用，并补充权限、审计和备份恢复演练。

验收：

- 完成一次空目录恢复演练。
- 未授权查询在召回前被过滤。
- 每个重要回答 claim 都绑定 evidence；证据不足时返回“不足以回答”。

整体第一轮实施预计 4～6 周。若只完成阶段 0～2，可在约 2 周内显著提升当前知识库的可靠性和可追溯性。

---

## 10. 评测与质量指标

### 10.1 数据完整性

- 历史论文映射覆盖率：100% 已匹配或明确待审核。
- 历史 QA 迁移完整率：100%。
- orphan QA / Evidence / Analysis：0。
- active QA 重复率：低于 1%，其余进入 duplicate candidate 队列。
- 索引记录数与 active 数据快照一致率：100%。

### 10.2 证据质量

- 核心论文阅读卡证据覆盖率：100%。
- 重要 QA 页码或章节定位覆盖率：阶段 2 达到 80%，稳定期达到 95% 以上。
- `unverified` QA 在默认结果中的比例持续下降。
- 错误页码、错误论文绑定属于阻断发布的问题。

### 10.3 检索质量

建立按问题类型分层的评测集：

- 术语和代码名精确查询。
- 中文/英文改写查询。
- 数值、参数、公式和定义查询。
- 单篇论文方法、结果和局限查询。
- 多篇论文比较和冲突证据查询。
- Research Direction 和时间过滤查询。
- 无答案和越权查询。

主要指标：

- Recall@5、Recall@10。
- MRR@10、nDCG@10。
- Evidence Hit Rate。
- Paper Coverage / Diversity。
- 无证据拒答准确率。
- P50/P95 查询延迟。
- 索引构建时间和内存占用。

### 10.4 运维质量

- 增量任务成功率和平均重试次数。
- dead letter 数量和最长滞留时间。
- active index 新鲜度。
- 中台不可用时的降级成功率。
- 备份恢复时间和恢复点目标。

---

## 11. 推荐代码结构演进

在当前包内渐进拆分，不需要立即重建整个仓库：

```text
qa_knowledge_mcp/
  domain/
    papers.py
    qa.py
    evidence.py
    analysis.py
    taxonomy.py
  storage/
    overlay_db.py
    migrations/
    artifacts.py
  hub/
    client.py
    models.py
  ingestion/
    legacy_qa.py
    identity.py
    evidence_alignment.py
    tasks.py
  retrieval/
    documents.py
    lexical.py
    dense.py
    fusion.py
    rerank.py
    evaluation.py
  indexing/
    build.py
    manifest.py
    publish.py
  mcp/
    paper_tools.py
    knowledge_tools.py
    admin_tools.py
```

迁移建议：

- 保留 `knowledge_base.py` 作为兼容 facade，逐步下沉实现。
- `build_kb.py` 演进为版本化 index builder，而不是直接覆盖固定目录。
- `mcp_server.py` 只负责依赖装配和工具注册，业务逻辑进入 service 层。
- `daily_digest.py` 继续负责日报适配，但发现结果通过覆盖层保存 Inbox 状态。
- 测试拆分为 unit、integration、migration 和 retrieval evaluation。

---

## 12. 风险与控制

| 风险 | 影响 | 控制措施 |
|---|---|---|
| 文献中台 ID 误匹配 | QA 绑定错误论文 | 多信号匹配、置信度、人工复核、保留原始映射 |
| Markdown 页码不可靠 | 生成错误引用 | 记录 locator quality，无法确认时只返回章节或文本匹配 |
| parser/chunker 更新 | Evidence link 失效 | 保存稳定 page/span/anchor，后台重对齐，不覆盖旧版本 |
| QA 质量参差 | 错误答案进入 Agent | lifecycle、审核状态、质量阈值、默认排除 unverified |
| taxonomy 漂移 | 历史统计不可比 | taxonomy version、deprecated、successor 和 assignment history |
| 索引与主数据不一致 | 已删除或未审核内容仍可检索 | immutable version、发布校验、active pointer、对账任务 |
| embedding 模型更换 | 全量重算和结果漂移 | embedding version 共存、离线评测、分批迁移 |
| MCP 泄露路径或全文 | 安全事故 | 返回字段白名单、ACL 前推、管理员工具分离、审计日志 |
| 过度设计 | 交付慢、维护重 | 先 SQLite + 本地索引，按指标触发 PostgreSQL 和外部组件 |
| 自动回答掩盖证据不足 | 形成虚假结论 | 最后实施、逐 claim 绑定证据、无证据拒答 |

---

## 13. 第一批开发任务

按优先级建议立即创建以下工作项：

1. `test-bootstrap`：统一安装、测试命令和 CI 基线。
2. `kb-audit`：生成当前 90/2402 数据质量与 hash 报告。
3. `hub-client`：封装中台 paper/read/reference/digest/status 接口。
4. `overlay-schema`：实现论文映射、QA version、Evidence、审核和任务表。
5. `legacy-paper-match`：完成 90 篇论文与中台 UUID 对齐。
6. `legacy-qa-import`：无损迁移 2402 条 QA，生成稳定 ID 和 provenance。
7. `evidence-alignment`：从 Markdown 恢复 page/section/span（当前已实现章节与正文段落保守对齐；页码/图表待中台全文结构支持）。
8. `evidence-pack-v2`：返回中台 ID、知识类型、版本、审核和定位质量。
9. `index-versioning`：不可变索引、manifest 校验、active pointer 和回滚。
10. `retrieval-eval`：建立回归问题集和检索指标报告。
11. `reading-card-v2`：结构化字段、Evidence 绑定和人工审核（当前已完成 Markdown 文档导入与统一检索接入，结构化审核待补）。
12. `search-knowledge`：主库与小方向库联合召回、过滤和排序（当前已实现 QA Pair + 原文段落检索；Topic/Decision 不作为 MCP 入口）。

第一批应优先完成 1～8。它们直接解决当前知识库最关键的身份、证据和数据治理问题，也是后续阅读卡、主题综述与自动回答的前置条件。

---

## 14. 最终建议

当前项目不需要推倒重建。现有 MCP、日报客户端、Evidence Pack、混合检索和离线索引都可以作为迁移基线，但知识库核心必须从“JSONL 中的 QA 数组”升级为“绑定 canonical Paper、拥有版本和审核状态、通过 Evidence 回到原文的知识实体”。

实施优先级应始终保持：

```text
论文身份
  → 原文证据
  → QA/Analysis 版本与审核
  → 增量任务和索引发布
  → 检索评测与优化
  → 主题综合
  → 带证据回答
  → 图谱和研究智能
```

只要前四项完成，当前项目就能从可用原型升级为可靠的实验室知识基础设施；图谱、推荐和跨论文智能应继续等待真实数据、查询日志和评测结果证明其必要性。
