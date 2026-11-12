# Lab Paper Knowledge Base Technical Design

> 版本：2026-08-07
> 范围：技术调研与概念设计，不包含 SQL Schema、ORM Model、详细字段或 QA Generation Pipeline。
> 目标规模：实验室内部几万至几十万篇论文。

---

## 1. Executive Summary

本方案建议把系统建设成一个以 **Paper 原文为 Source of Truth**、以 **PostgreSQL + pgvector 为一致性核心**、以 **对象存储保存 PDF 与解析产物**、以 **统一检索层向 MCP / Agent 提供能力** 的长期论文知识库。

核心结论：

1. **不要按研究方向拆成文件夹或独立数据库。** 默认使用统一数据库，通过 hierarchical taxonomy、multi-label assignment、collection 和可选 namespace 进行逻辑区分。只有存在权限、合规、生命周期或资源配额差异时才建立 namespace 级隔离。
2. **Research Direction、Topic、Tag、Collection、Namespace 必须分工。**
   - Research Direction：实验室维护的稳定层级分类体系。
   - Topic：从语料或研究活动中形成的可演化语义主题。
   - Tag：轻量、扁平、细粒度描述词。
   - Collection：人为策展的论文集合或工作清单。
   - Namespace：安全、租户、索引或生命周期边界，不应冒充学科分类。
3. **QA 必须是独立的一等实体，同时也是可检索文档。** QA 不应仅作为 Paper JSON 附件；它应与 Paper、Evidence、Chunk、版本和 provenance 显式关联，并分别建立 lexical 与 dense index。
4. **Paper、Section、Chunk、Analysis、QA、Evidence 必须保留可追溯关系。** Analysis 和 QA 都是 Derived Knowledge，任何可证据化结论都应能够回到原文片段、页码或结构化位置。
5. **MVP 不需要独立向量数据库，也不建议一开始引入 Neo4j。** 几万至几十万篇论文、数百万级 chunk 的内部系统，PostgreSQL、全文检索和 pgvector 通常足够。先通过分区、批量索引、HNSW/IVFFlat、查询过滤和缓存优化；出现明确瓶颈后再拆分 OpenSearch 或 Qdrant/Milvus。
6. **检索不是一个单一 `search`。** 推荐以查询规划器选择 QA、Paper Analysis、原文 Chunk 或 Citation Graph，执行 structured filter + BM25 + dense retrieval + reranker，并将结果统一为带 provenance 的 Evidence Bundle。

最终推荐 MVP：

```text
Collectors / Metadata Providers
          |
          v
Ingestion Orchestrator
          |
          +--> Object Storage: PDF, source files, parser artifacts
          |
          +--> PostgreSQL:
               metadata, taxonomy, relations, versions,
               analysis, QA, evidence, citations,
               full-text indexes, pgvector embeddings
          |
          v
Unified Retrieval Service
          |
          +--> REST / internal API
          +--> MCP tools
          +--> Agent / SICON
```

---

## 2. Requirements and Design Constraints

### 2.1 Functional scope

系统需要管理：

- Paper、Author、Venue、metadata、PDF / full text
- PDF parser outputs、Section、Chunk
- PaperAnalysis
- 外部现有 pipeline 生成的 QuestionAnswerPair
- QA 与 Paper / Evidence / Chunk 的关联
- ResearchDirection、Topic、Tag、Collection
- Citation / Related Paper
- lexical、dense、hybrid retrieval
- Agent / MCP access
- 更新、版本、去重、审计与 provenance

### 2.2 Explicitly out of scope

- QA Generation Pipeline
- QA prompt、candidate generation、verification、生成模型选择
- 详细字段设计
- SQL Schema、ORM Model
- 系统实现代码

### 2.3 Non-functional priorities

优先级从高到低：

1. 可追溯性与数据正确性
2. 长期可维护性
3. 检索质量
4. 增量更新与幂等重跑
5. 开发与运维复杂度
6. 可扩展性
7. 极限吞吐量

---

## 3. GitHub Repository Survey

下表的 Stars 是 2026-08-07 调研时的约数；Stars 会持续变化，不应作为技术选型的主要依据。

| Repository                                                                   | Stars（约） | Purpose                                 | 核心技术 / 特征                                                                         | 数据组织与 Retrieval                                                                 | 值得借鉴                                                                         |
| ---------------------------------------------------------------------------- | ----------: | --------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| [Future-House/paper-qa](https://github.com/Future-House/paper-qa)             |         7k+ | 科学文献高准确率 agentic RAG            | metadata-aware embedding、全文索引、chunk evidence、reranking、citation-grounded answer | 文档索引、chunk evidence、context summaries、answer history；支持外部 DB / vector DB | 查询分阶段、Evidence 汇聚、答案引用、已有答案可再次索引                          |
| [docling-project/docling](https://github.com/docling-project/docling)         |        40k+ | 将复杂文档转换为适合 GenAI 的结构化表示 | PDF layout、reading order、table、figure、formula、多格式转换                           | 先构建统一文档结构，再导出 JSON / Markdown，并支持面向 RAG 的切分                    | Parser Adapter、规范化文档树、表格/图片保真、解析产物版本化                      |
| [paperless-ngx/paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) |        30k+ | 长期文档归档与检索                      | OCR、consumer pipeline、metadata、tags、correspondents、全文搜索、任务队列              | 原文件与归档文件分离；异步 ingestion；标签和文档类型管理                             | 可运营的 ingestion 状态机、去重、原件保留、失败重试、权限和任务可观测性          |
| [zotero/zotero](https://github.com/zotero/zotero)                             |        10k+ | 学术文献管理                            | bibliographic metadata、attachments、collections、tags、notes、sync                     | Item 与附件、collection、tag 分离；同一 Item 可进入多个 collection                   | Collection 不是 taxonomy；附件与 bibliographic item 分离；同步与用户编辑冲突处理 |
| [allenai/s2orc-doc2json](https://github.com/allenai/s2orc-doc2json)           |        470+ | 科学论文 PDF/TEX/JATS 到统一 JSON       | GROBID、TEI XML、PDF2JSON、TEX2JSON、JATS2JSON                                          | 使用统一的 S2ORC JSON 表达标题、作者、正文、参考文献和引用位置                       | 多解析来源归一化、科学论文结构、引用上下文和 parser provenance                   |
| [allenai/science-parse](https://github.com/allenai/science-parse)             |         2k+ | 科学 PDF metadata / references 解析     | JVM、PDF parsing、bibliography extraction                                               | 将 PDF 提取为结构化 metadata 与 references                                           | 解析服务化、科学文献专用 metadata extraction；但项目活跃度需谨慎评估             |
| [run-llama/llama_index](https://github.com/run-llama/llama_index)             |        40k+ | 数据接入、索引与 Agent RAG 框架         | nodes、documents、metadata filters、retrievers、vector stores、query engines            | Document -> Node；索引与存储可替换；组合检索器                                       | Document/Node 抽象、metadata filter、retriever composition、存储适配器边界       |
| [deepset-ai/haystack](https://github.com/deepset-ai/haystack)                 |        20k+ | 生产级 RAG / search pipeline            | component DAG、document stores、BM25、embedding retriever、ranker                       | Document 作为统一检索单位；pipeline 显式组合                                         | Hybrid retrieval pipeline、组件契约、评估与可观测性                              |
| [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG)                           |        20k+ | 轻量 graph + vector RAG                 | KV、vector、graph、document-status 四类 store；local/global/hybrid/naive/mix 查询       | Chunk、entity、relation 分层；支持增量更新与 selective delete                        | 图与向量的职责分离、查询模式、增量图更新；适合作为后期能力而非 MVP 基线          |
| [microsoft/graphrag](https://github.com/microsoft/graphrag)                   |        30k+ | 面向复杂语料的 graph-based RAG          | entity/relation extraction、community summaries、local/global search                    | 从 text units 提取实体关系，形成社区与多级报告                                       | 跨论文主题总结、global question；同时展示了图构建成本和运维复杂度                |
| [HKUDS/RAG-Anything](https://github.com/HKUDS/RAG-Anything)                   |        10k+ | 多模态文档 RAG                          | text/table/image/equation parsing，关联式检索                                           | 多模态内容被转换为可连接的检索对象                                                   | 学术 PDF 中表格、图、公式不应被永久降级为纯文本                                  |
| [OpenAlex/openalex-guts](https://github.com/ourresearch/openalex-guts)        |         1k+ | OpenAlex 数据构建与开放学术图谱基础设施 | works/authors/sources/institutions/topics/concepts、citation links                      | 以 Work 为中心，作者、来源、主题、引用关系独立建模                                   | 外部 canonical ID、metadata merge、citation graph、开放学术实体对齐              |

### 3.1 Survey observations

成熟项目反复出现以下共性：

- **原始文件、解析产物和业务实体分开。**
- **检索单位通常不是 Paper 本身，而是派生的 Node / Chunk / Text Unit / Evidence。**
- **metadata filter 与语义检索组合，而不是只做向量相似度。**
- **答案或分析结果要携带 evidence / citation，而不是只保存无来源文本。**
- **Collection 更接近用户策展，不等于知识分类。**
- **大规模图谱系统通常将图构建视为额外索引，而不是替代关系数据库中的事实主数据。**

---

## 4. Repository Deep Dive

## 4.1 PaperQA2

### 实际结构与流程

仓库将核心包放在 `src/paperqa`，并提供 docs、configs、packages 和 tests。其默认流程明确划分为：

1. Paper Search：查候选论文并加入状态。
2. Gather Evidence：对 query 向量化，召回 chunk，生成 query-contextual summaries，再重排。
3. Generate Answer：用最优 summaries 形成带引用的回答。

项目支持 metadata provider、全文搜索、embedding、外部 vector DB、索引复用和已有 answer 索引。它还将 paper search、evidence gathering、answer 作为 agent 可调用的不同动作，而不是单一黑盒接口。

### 对本项目最值得借鉴

- **借鉴 retrieval orchestration，不复制其回答生成。**
- QA / answer 可以独立进入搜索索引。
- Retrieval 返回的是带文献定位的 evidence，而不是只有 chunk 文本。
- 查询过程允许先宽后窄、多轮改写，但底层工具职责明确。
- Chunk 召回后再做 contextual summarization / reranking，说明 dense top-k 不能直接等同于最终证据。

### 不应直接复制

- PaperQA 更接近查询时 RAG runtime，而本项目是长期知识库。
- 本系统应以持久化、版本化和可治理的数据模型为核心，不能把 agent session state 当主数据库。

## 4.2 Docling

### 实际结构与流程

Docling 的价值不在数据库，而在将 PDF、Office、HTML 等转换成保留 reading order、section hierarchy、table、figure、formula 和 page location 的统一文档表示。其 parser 和 exporter 分层，使后续 chunking 不必直接依赖某个 PDF 引擎的私有输出。

### 对本项目最值得借鉴

- **借鉴 Canonical Parsed Document 中间层。**
- 不让 Section / Chunk 直接绑定到 GROBID、Docling 或 MinerU 的原始格式。
- Parser output 保存为不可变 artifact；归一化层生成内部文档树。
- Chunking 应使用 heading、paragraph、table 等语义边界，不只是固定 token 长度。
- 表格、图、公式应保留独立内容对象和原页定位，Chunk 只引用它们。

## 4.3 S2ORC Doc2JSON

### 实际结构与流程

项目支持 PDF、LaTeX 和 JATS 等不同来源，经 GROBID / TEI XML 或专用 parser 归一化为 S2ORC JSON。代码中将统一 schema 与 parser 实现分开，并特别处理作者、bibliography、reference spans 和 citation context。

### 对本项目最值得借鉴

- **借鉴科学论文专用的归一化结构和引用定位。**
- 同一 Paper 可以有多个 SourceRepresentation：PDF、LaTeX、JATS。
- Parser run 必须带 parser name/version/config，才能在 parser 升级后可重放。
- Citation 不只是 Paper A 引用 Paper B；还需要保留引用发生在哪一 Section / Chunk。
- PDF 解析是概率性过程，应允许 parse quality、人工修正和替代 parser 共存。

## 4.4 LightRAG

### 实际结构与流程

LightRAG 明确区分 KV、Vector、Graph 和 Document Status 四类存储，并支持 local、global、hybrid、naive 和 mix 查询模式。它还强调增量更新、selective deletion、多个 parser、多个 chunking 策略以及 chunk/entity/relation 的 source relation。

### 对本项目最值得借鉴

- **借鉴“图是索引层，不是所有数据的唯一真相源”。**
- Document Status 是必要的一等运营概念：queued、parsed、indexed、failed 等状态不应散落在日志中。
- 对实体、关系、chunk 分别建立向量只是可选高级索引。
- 删除论文时要能追踪并删除该论文派生的 chunk、embedding、graph edge 和 cache。

### 不建议 MVP 复制

- 图谱实体抽取需要大量 LLM 成本，更新逻辑复杂。
- 实验室首要查询多为 metadata filter、topic、QA 和 chunk evidence，关系数据库 + hybrid retrieval 已能覆盖多数需求。

## 4.5 Zotero + Paperless-ngx

这两者不是学术 RAG 项目，但在长期维护方面比多数 demo 更有参考价值。

### Zotero 的启示

- bibliographic item 与 PDF attachment 分离。
- 同一论文可以属于多个 Collection。
- Tag 是扁平描述，不承担稳定 taxonomy 的职责。
- 用户编辑、同步、附件和引用 metadata 需要不同生命周期。

### Paperless-ngx 的启示

- ingestion 需要异步队列、幂等处理、失败重试、去重和可见状态。
- 原始文件和归档/转换版本要同时保留。
- 自动分类结果与人工 metadata 可以共存。
- 长期系统需要后台任务、操作审计和管理 UI，不能只有 notebook pipeline。

---

## 5. Existing Architecture Patterns

| Pattern                                    | 优点                                                         | 缺点                                                           | 一致性 / Retrieval                                     | 适用性                                 |
| ------------------------------------------ | ------------------------------------------------------------ | -------------------------------------------------------------- | ------------------------------------------------------ | -------------------------------------- |
| SQLite + FAISS                             | 本地简单、零运维、适合个人原型                               | 并发、权限、增量备份、分布式服务较弱；两套存储易漂移           | 事务只覆盖 metadata；vector index 需单独同步           | 单人 PoC，不适合作为实验室长期主系统   |
| PostgreSQL + pgvector                      | 单一事务边界；关系、JSON、全文、向量、过滤统一；团队熟悉度高 | 极大规模向量、复杂 BM25 排名和高并发搜索不如专用系统           | 一致性最佳；metadata filter 与 vector join 自然        | **推荐 MVP**                     |
| Relational DB + Vector DB + Object Storage | 各自专长；向量可独立扩容                                     | 双写、一致性、删除传播、备份与版本管理复杂                     | 需要 outbox / CDC / reconciliation                     | vector 查询成为明确瓶颈后              |
| PostgreSQL + OpenSearch + Object Storage   | BM25、filter、facet、highlight、hybrid 与日志生态强          | 索引最终一致；集群运维和 mapping 管理复杂                      | PostgreSQL 为 source of truth，OpenSearch 为可重建索引 | 高级全文检索、多语言、复杂聚合或高 QPS |
| Knowledge Graph + Vector Retrieval         | 适合跨论文关系、多跳和全局主题                               | 图构建昂贵，实体消歧困难，更新和评估复杂                       | 图只能作为 derived index；需保留 source chunk          | Phase 3，且有明确 graph query          |
| MongoDB + Vector Search                    | JSON ingest 灵活、开发快                                     | 多实体关系、taxonomy、版本、citation join 不如 PostgreSQL 直观 | 文档模型适合 parser artifact，不是最佳全局关系主库     | 团队已有强 Mongo 经验时可考虑          |

### 5.1 General lesson

主数据与索引要明确分离：

- **System of record**：Paper、关系、版本、人工编辑、taxonomy、QA provenance。
- **Immutable artifacts**：PDF、LaTeX、parser raw output、normalized document JSON。
- **Rebuildable indexes**：full-text index、embedding、reranker cache、knowledge graph。

任何索引都应能够从主数据和 artifact 重建。

---

## 6. Lessons Learned

1. Parser 输出必须规范化，避免业务层耦合单一 PDF 引擎。
2. Chunk 是有版本的派生对象，不是稳定的永恒实体。
3. Evidence 是“对来源的引用”，不应等同于复制一份 chunk 文本。
4. QA 和 Analysis 必须记录 provenance、版本和适用状态。
5. Taxonomy 是治理资产，不应由无约束的 LLM 输出直接改写。
6. Collection 是用户工作流，Topic 是语义发现，Tag 是描述词。
7. Hybrid retrieval 的第一步是 structured filtering；不是把 BM25 和 vector 分数简单相加。
8. 图谱是跨文档推理的可选增强，不是 MVP 的必要前提。
9. Ingestion 和 Retrieval 应是两个相对独立的 bounded context。
10. Agent tool 应提供稳定的领域能力，而不是暴露数据库查询细节。

---

## 7. Proposed System Architecture

```text
Paper Sources
  arXiv / DOI / Crossref / OpenAlex / Semantic Scholar / manual upload
        |
        v
Collector & Identity Resolution
  canonical IDs, metadata merge, dedup candidates
        |
        +--------------------------+
        |                          |
        v                          v
Object Storage                PostgreSQL
PDF / TEX / JATS              Paper / Author / Source
raw parser outputs            ingestion state / provenance
normalized document
        |                          |
        +------------+-------------+
                     v
Parser & Normalization
  DocumentTree -> Section -> Block -> Chunk
                     |
                     v
Derived Knowledge Import
  PaperAnalysis import
  Existing QA import
  Evidence alignment
                     |
                     v
Taxonomy Assignment
  human taxonomy + automated suggestions
                     |
                     v
Indexing
  PostgreSQL FTS + pgvector
  optional OpenSearch / vector DB / graph index
                     |
                     v
Unified Retrieval Service
  query plan -> candidate retrieval -> fusion -> rerank
                     |
          +----------+-----------+
          |                      |
          v                      v
      REST / API               MCP
                                 |
                                 v
                         Agent / SICON
```

### 7.1 Architectural boundaries

- **Collector**：发现论文和获取 metadata，不解析内容。
- **Artifact Store**：保存不可变文件，不承担语义查询。
- **Parser Adapter**：调用 Docling / GROBID / MinerU 等。
- **Normalizer**：生成内部统一 DocumentTree。
- **Chunker**：从特定 DocumentTree version 生成 ChunkSet。
- **QA Importer**：只导入已有 QA，做 identity validation 和 evidence alignment。
- **Taxonomy Service**：维护 direction tree 与 assignment。
- **Indexer**：构建可重建索引。
- **Retrieval Service**：唯一负责召回、融合、重排和 provenance assembly。
- **MCP/API**：稳定的外部领域接口，不暴露内部表。

---

## 8. Conceptual Data Model

本节仅为 ER / responsibility level，不定义字段。

### 8.1 Core entities

| Entity             | Responsibility                                                                 |
| ------------------ | ------------------------------------------------------------------------------ |
| ResearchDirection  | 实验室治理的层级研究方向节点                                                   |
| Paper              | 论文的 canonical scholarly work                                                |
| PaperSource        | arXiv、DOI、OpenAlex、Semantic Scholar、上传来源等外部身份与 metadata snapshot |
| Author             | 作者实体；允许外部 ID 对齐和待消歧状态                                         |
| PaperArtifact      | PDF、LaTeX、JATS、supplementary material 等原始文件                            |
| ParseRun           | 一次 parser 执行及其版本、配置、状态和产物                                     |
| DocumentVersion    | 归一化后的论文结构版本                                                         |
| Section            | 文档层级节点                                                                   |
| ChunkSet           | 某一 chunking 策略对 DocumentVersion 的派生版本                                |
| Chunk              | 最小主要检索单元，保持文档位置和父层级                                         |
| PaperAnalysis      | 对 Paper 的结构化分析结果及版本                                                |
| QuestionAnswerPair | 外部生成并导入的 QA 知识实体                                                   |
| Evidence           | QA / Analysis claim 对原文位置的可追溯引用                                     |
| Embedding          | 对某一可检索对象在特定模型版本下的向量表示                                     |
| Tag                | 扁平、细粒度、低治理成本的描述词                                               |
| Topic              | 可演化的语义主题，可人工或算法发现                                             |
| Collection         | 人为策展、项目任务或阅读清单                                                   |
| Citation           | Paper 到 Paper 的有向引用关系                                                  |
| RelatedPaper       | 非 citation 的相似、扩展、复现或人工关联                                       |
| Namespace          | 可选的权限、租户、索引与生命周期边界                                           |

### 8.2 Key relationships

```text
Paper N:M Author
Paper N:M ResearchDirection
Paper N:M Tag
Paper N:M Topic
Paper N:M Collection

Paper 1:N PaperSource
Paper 1:N PaperArtifact
PaperArtifact 1:N ParseRun
ParseRun 1:1..N DocumentVersion
DocumentVersion 1:N Section
DocumentVersion 1:N ChunkSet
ChunkSet 1:N Chunk

Paper 1:N PaperAnalysis
Paper 1:N QuestionAnswerPair
QuestionAnswerPair N:M Evidence
PaperAnalysis N:M Evidence
Evidence N:1 or N:M Chunk

Paper N:M Paper through Citation
Paper N:M Paper through RelatedPaper

Chunk 1:N Embedding
QuestionAnswerPair 1:N Embedding
PaperAnalysis 1:N Embedding
Paper 1:N Embedding (optional abstract/title representation)
```

### 8.3 Important modeling decisions

- Paper 与 ResearchDirection 是 N:M；assignment 上表达 primary / secondary，而不是把 primary 做成 Paper 的固定字段。
- Section 属于 DocumentVersion，Chunk 属于 ChunkSet。Parser 或 chunking 改变时生成新版本，不覆盖旧对象。
- Evidence 是定位层，可引用单一 Chunk、多个 Chunk、Section 范围、页面区域或外部 artifact。
- Embedding 不是实体内容本身，而是“对象版本 + embedding model/version”的可重建派生物。
- Citation 与 RelatedPaper 分开：citation 是可验证 bibliographic edge；related 是算法或人工关系。

---

## 9. Research Direction / Taxonomy Design

## 9.1 Roles

### Research Direction

- 稳定、有人负责、可层级化。
- 回答“这项工作属于实验室哪个研究领域”。
- 适合导航、权限、统计、roadmap 和检索过滤。
- 节点可多父级，但展示上应尽量保持近似树；如允许 DAG，治理规则必须明确。

### Topic

- 语义上比 Direction 更动态。
- 回答“这一批论文当前讨论什么问题”。
- 可以由聚类、关键词、LLM 建议或研究人员创建。
- 可以过期、合并、拆分，不应直接决定权限。

### Tag

- 扁平词汇，如 `episodic-memory`、`retrieval`、`long-context`。
- 低成本、可大量增长。
- 用于细粒度筛选和个人/团队标注。
- 需要 synonym / alias 治理，防止同义词爆炸。

### Collection

- 有明确 owner 或 purpose 的策展集合，如“2026 Agent Memory Survey”“组会待读”“项目 A baseline”。
- 同一论文可进入任意多个 Collection。
- Collection 不表达学科真理，也不自动继承层级分类。

### Namespace

- 仅当需要访问控制、租户隔离、数据保留策略、独立索引或成本配额时使用。
- 如果所有方向都属于同一实验室并共享论文，MVP 可只有一个默认 namespace。
- 不建议用 namespace 表示 `LLM/Agent/Memory`；那会造成重复数据和跨方向检索困难。

## 9.2 Logical vs physical isolation

### 推荐默认：统一物理存储 + 逻辑区分

理由：

- 一篇论文通常跨多个方向。
- Author、Citation、PDF 和 Chunk 可共享，避免重复。
- Cross-direction retrieval 与趋势分析更自然。
- 统一去重、备份、迁移和 embedding 管理。

### 需要物理或强逻辑隔离的条件

- 未公开论文或保密项目。
- 合作单位限制。
- 不同 license / retention policy。
- 极端规模或独立运维团队。
- 某方向要求完全不同的 embedding / parser / index SLA。

即使物理隔离，也应保留 global canonical paper identity，避免同一论文在多个库中失去关联。

## 9.3 Classification workflow

推荐：

```text
Human-maintained taxonomy
        +
Rule-based deterministic signals
        +
LLM multi-label suggestions
        +
Embedding nearest-neighbor assistance
        +
Human review for uncertain / high-impact assignments
```

步骤：

1. 管理员创建、移动、合并、废弃 Direction node。
2. 规则根据 venue、collection、关键词或 source 给出高精度候选。
3. LLM 基于 title、abstract、analysis 给出 primary / secondary 建议和解释。
4. Embedding 以已人工确认论文作为近邻参考。
5. 分类置信度高时自动接受 secondary；primary 或新节点建议进入 review queue。
6. 每次分类都记录 taxonomy version 和 classifier provenance。

### 新方向加入

- 新增 node，不迁移论文物理位置。
- 对候选论文做 backfill classification。
- 老节点可以 deprecated，但不要删除历史 assignment。
- 节点合并通过 canonical successor 表达，保留历史统计可重放。

## 9.4 QA direction inheritance

推荐：

- QA 默认继承 Paper 的全部 ResearchDirection，作为查询过滤的 denormalized index metadata。
- QA 仍可拥有自己的 optional direction assignment。
- 当 QA 是 cross-paper、只涉及论文某个局部方向，或人工判断与 Paper primary 不同，使用 QA-level override / supplemental assignment。
- 继承值是可重建索引，不应复制为不可追踪的独立事实。

---

## 10. Existing QA Data Organization

## 10.1 Comparison

| Option                            | 优点                                       | 缺点                                                      | 结论                                       |
| --------------------------------- | ------------------------------------------ | --------------------------------------------------------- | ------------------------------------------ |
| A. Paper 附属 JSON                | 导入简单、读取整篇 QA 快                   | 难独立检索、难版本化、难去重、难 evidence N:M、并发编辑差 | 仅适合保存原始 import payload              |
| B. QA 独立实体                    | 可检索、评分、版本、人工编辑、生命周期清晰 | 需要额外关系和索引                                        | 必须采用                                   |
| C. QA -> Evidence -> Chunk        | 可追溯、多 chunk、parser/chunk 更新可对齐  | 导入与对齐复杂                                            | 必须采用                                   |
| D. QA 同时作为 Retrieval Document | 用户问题可直接命中已有答案，低延迟         | 需处理旧版本、质量和过期答案                              | 必须采用，但只索引 active/eligible version |

### 推荐：B + C + D，A 仅用于原始 payload 归档

```text
Paper
  |
  +--> QA Family / Logical QA
          |
          +--> QA Version 1
          +--> QA Version 2
          |
          +--> Evidence links
                  |
                  +--> Chunk / Section / page span
```

## 10.2 QA lifecycle

概念状态：

- imported
- validated
- active
- superseded
- deprecated
- rejected
- needs_review

状态不等于版本。一次人工修改或外部 pipeline 重生成应形成新版本；旧版本保留用于审计，但不进入默认检索。

## 10.3 Provenance and versioning

每个 QA version 在概念上必须知道：

- 来自哪个 external pipeline run / source payload。
- 针对哪个 Paper version 或 DocumentVersion。
- 由何种方式建立 evidence link：原生 offsets、文本对齐、人工确认。
- 是否人工编辑。
- quality / verification 信息来自哪个系统。
- 它替代或派生自哪个 QA version。

## 10.4 Deduplication

采用多阶段去重：

1. external stable ID 精确匹配。
2. 同 Paper 内 normalized question exact/hash。
3. question embedding + answer similarity 形成 duplicate candidate。
4. evidence overlap 判断是否实际上是同一 QA。
5. 人工或规则决定 merge、alternate wording 或 distinct。

不要只按 question string 去重，因为相同问题可能针对不同论文、不同时间范围或不同 evidence。

## 10.5 Evidence association

优先级：

1. 外部 pipeline 已提供 paper ID + page/span/chunk ID：直接映射并验证。
2. 提供 evidence text：在对应 DocumentVersion 中做 lexical span alignment。
3. 无显式 evidence：用 retrieval 生成候选链接，但标记为 machine-aligned / unverified。
4. 完全无法定位：允许 QA 存在，但默认降低检索权重并提示无可验证 evidence。

Parser 或 chunking 更新时，不应立即让旧 QA 失效。Evidence 还应保留更稳定的 page/span 或 normalized block anchor，用于重映射到新 ChunkSet。

## 10.6 QA as retrieval document

建议至少建立三种表示：

- question-only lexical / dense representation
- question + concise answer representation
- optional question + answer + direction/topic metadata representation

返回 QA 时必须同时返回：

- QA version/status/quality
- Paper identity
- Evidence citations
- applicable directions
- 是否人工编辑或已 superseded

---

## 11. Paper Ingestion Architecture

```text
1. Discover / Submit
2. Resolve Identity
3. Deduplicate
4. Fetch & Merge Metadata
5. Acquire Artifact
6. Parse
7. Normalize Document
8. Build Section / ChunkSet
9. Embed
10. Assign Research Directions
11. Import Paper Analysis
12. Import Existing QA
13. Align Evidence
14. Build Indexes
15. Publish active version
```

### 11.1 Identity resolution

确定 canonical Paper 之前，按可靠度组合：

- DOI
- arXiv ID + version
- PMID / ACL Anthology / Semantic Scholar / OpenAlex ID
- normalized title + author + year
- PDF fingerprint

外部 metadata 不直接覆盖人工确认值。应保存 provider snapshots，由 merge policy 生成当前 canonical view。

### 11.2 Idempotency

每个 pipeline stage 的输入由内容 hash、上游 version 和 config version 决定。相同输入重复执行应复用结果；parser、chunker、embedding model 或 taxonomy version 改变时生成新派生版本。

### 11.3 PDF and artifacts

- PDF 不建议作为数据库大字段保存。
- 对象存储保存原始文件、parser raw output、normalized JSON、图片/表格裁剪等。
- PostgreSQL 保存 artifact identity、hash、location、media type、provenance 和 lifecycle。
- 本地 MVP 也可使用 S3-compatible filesystem abstraction；这样以后迁移 MinIO / cloud object storage 不改业务接口。

### 11.4 Publish model

处理过程可以产生多个 working version，但只有通过基本质量检查的版本成为 active：

- metadata identity validated
- parser completed
- chunk coverage 达标
- embedding complete
- QA import validation complete or explicitly skipped

索引只切换 active pointer，避免用户查询到半完成状态。

---

## 12. Retrieval Architecture

## 12.1 Retrieval targets

| Target             | 适用问题                                               | 返回内容                      |
| ------------------ | ------------------------------------------------------ | ----------------------------- |
| Paper metadata     | 年份、作者、venue、方向、collection、citation count 等 | Paper summaries / IDs         |
| QA                 | 与已有问题高度相似、需要快速可靠答案                   | QA + paper + evidence         |
| PaperAnalysis      | 方法、贡献、限制、实验设置等结构化查询                 | analysis fragments + evidence |
| Chunk              | 新问题、细节核验、QA/analysis 不足                     | 原文片段 + location           |
| Citation / Related | 上下游工作、演进、复现、相似论文                       | graph edges + paper metadata  |

## 12.2 Agent-oriented pipeline

```text
User Query
   |
   v
Query Understanding
  intent, entities, date, venue, author,
  research direction, expected evidence depth
   |
   v
Structured Filter Plan
   |
   +--> QA retriever
   +--> Analysis retriever
   +--> Chunk BM25 retriever
   +--> Chunk dense retriever
   +--> Paper metadata retriever
   +--> Citation retriever
   |
   v
Candidate normalization
   |
   v
Fusion
  weighted RRF preferred over raw-score addition
   |
   v
Reranker
   |
   v
Diversity / paper coverage control
   |
   v
Evidence Bundle
  source type, paper, section/page, score,
  provenance, active version, direction
```

### 12.3 Structured filters

过滤应尽可能前推：

- namespace / ACL
- active version
- date range
- venue
- author
- primary / secondary direction
- topic / tag / collection
- paper IDs
- language
- artifact availability
- QA status / quality threshold

### 12.4 BM25 + dense + reranker

- BM25 擅长术语、模型名、数据集名、公式符号和精确短语。
- Dense retrieval 擅长改写、概念相似和跨语言表达。
- RRF 可避免直接比较不可校准的 BM25 与 cosine 分数。
- Reranker 只处理融合后的有限候选，结合 query、文本、标题、section heading 和 metadata。
- 最终增加 diversity 约束，避免 top-k 全来自同一篇论文或重复 chunk。

## 12.5 When to search QA vs Analysis vs Chunk

推荐 routing policy：

1. **优先 QA**：
   - 问题与已有 QA 高度相似。
   - QA active、质量合格且 evidence 完整。
   - 用户需要快速直接答案。
2. **优先 Analysis**：
   - 问贡献、方法、限制、实验、数据集、结论等已结构化维度。
   - 需要比较多篇论文的同一属性。
3. **必须搜索 Chunk**：
   - QA / Analysis 召回不足。
   - 用户要求原文证据、细节、数值、定义、公式或引用核验。
   - 查询是新的、组合式的或跨 paper。
4. **QA 命中后仍可补 Chunk**：
   - QA evidence 不完整。
   - QA 较旧，Paper / parser / analysis 已更新。
   - 用户要求高置信、逐条证据。
5. **趋势 / 关系问题**：
   - 先用 metadata/taxonomy/citation 缩小候选，再在 Analysis/Chunk 中取证。

不要让 Agent 自由猜测底层索引。Retrieval service 应支持 `mode=auto|qa|analysis|chunk|paper|citation`，auto 由服务端 planner 执行，Agent 可以显式覆盖。

## 12.6 Evaluation

建立固定评测集：

- metadata filter correctness
- paper recall@k
- evidence recall@k
- QA exact / semantic retrieval
- direction-filtered retrieval
- citation grounding precision
- stale/superseded leakage rate
- latency、index freshness、cost

没有评测集时，不应凭主观感觉决定是否引入图谱或独立向量数据库。

---

## 13. Database Technology Selection

## 13.1 PostgreSQL + pgvector

### Why it is enough for MVP

- Paper、Author、Direction、QA、Evidence、Citation 都高度关系化。
- PostgreSQL 可同时承担事务、JSON artifact metadata、全文索引、filter 和 vector similarity。
- pgvector 支持 exact search 以及 HNSW / IVFFlat 等近似索引。
- 同一查询中可先做权限和 taxonomy filter，再做向量召回。
- 单一备份与恢复流程降低实验室运维成本。

### Practical scale judgment

几万至几十万 Paper 往往对应数百万至一两千万 Chunk，是否需要独立 vector DB 取决于：

- 向量维度与模型数量
- active embedding version 数量
- 查询并发和 SLA
- filter 选择性
- 索引构建窗口
- 硬件内存与磁盘

不能只按 Paper 数量判断。MVP 应先压测真实 chunk 分布。

## 13.2 When OpenSearch becomes justified

出现以下多个条件时考虑：

- 复杂 BM25、highlight、facet、aggregation 成为核心产品能力。
- 中英文 analyzer、同义词、字段权重调优需求明显。
- 搜索 QPS 或索引更新吞吐明显高于主库承载能力。
- 希望独立扩展搜索节点并接受最终一致性。
- 需要更成熟的 keyword + vector hybrid search operational tooling。

PostgreSQL 仍是 source of truth；通过 outbox/CDC 构建 OpenSearch index。

## 13.3 When Qdrant / Milvus / Weaviate becomes justified

考虑条件：

- 向量规模与 QPS 已经被压测证明是 PostgreSQL 瓶颈。
- 多 embedding collection、多租户向量隔离或向量生命周期非常复杂。
- 需要独立扩容、分片、副本或 GPU-oriented vector infra。
- 团队能够承担第二套状态系统和一致性修复。

倾向：

- Qdrant：相对易运维，metadata filter 与 hybrid 能力强，适合中等规模独立 vector service。
- Milvus：更适合超大向量规模和专门的分布式向量基础设施。
- Weaviate：对象 + vector 开发体验好，但会与 PostgreSQL 业务实体产生职责重叠。

## 13.4 MongoDB

适合 parser raw JSON 或团队强依赖文档模型的情况，但本项目的多对多关系、版本、taxonomy、citation 和 evidence join 使 PostgreSQL 更自然。没有既有组织标准时，不推荐作为主库。

## 13.5 Neo4j

MVP 不需要。Citation 可以用 PostgreSQL edge table 表达；常见一跳、两跳和相关论文查询足够。只有当以下条件成立时再引入：

- 真实用户频繁执行多跳关系查询。
- 图算法、community、path explanation 产生可测量价值。
- 已解决 entity resolution 与增量图更新。
- 有专门维护成本预算。

即便引入，Neo4j 也是 derived graph index，不是 Paper/QA 主数据源。

## 13.6 Object Storage

建议使用：

- PDF 和 supplementary files 体积大。
- parser raw artifacts、normalized JSON、images/tables 可版本化。
- 支持 content hash、生命周期和低成本备份。
- 数据库只保存 locator 和 metadata。

MVP 可使用 MinIO 或具有 S3-compatible interface 的本地存储；若部署环境已有 NAS，也应通过统一 artifact interface 封装。

## 13.7 Final selection

### MVP

```text
PostgreSQL
  + native full-text search
  + pgvector
Object Storage
Redis (optional cache / queue broker)
Worker queue
```

### Scale-up

```text
PostgreSQL as source of truth
Object Storage
OpenSearch for advanced lexical/hybrid search
Qdrant or Milvus only when vector benchmarks require it
Neo4j only for validated graph use cases
Outbox / CDC for index synchronization
```

---

## 14. MCP / API Design

## 14.1 Design principles

- Tool 面向稳定任务，不面向数据库表。
- 搜索 Tool 与详情 Tool 分开。
- 每个搜索结果返回 ID、摘要、score、source type 和 provenance。
- Tool 接受 structured filters，但限制参数复杂度。
- 所有 Tool 默认只返回 active、authorized、non-deprecated 数据。
- 大结果集使用 cursor，避免一次返回全文。

## 14.2 Proposed tools

| Tool                         | Responsibility                            | Notes                                                                    |
| ---------------------------- | ----------------------------------------- | ------------------------------------------------------------------------ |
| `search_papers`            | 按自然语言和结构化条件搜索 Paper          | metadata-first，可选 title/abstract/analysis relevance                   |
| `get_paper`                | 获取单篇 Paper 的 canonical overview      | 不返回整篇 chunks                                                        |
| `search_knowledge`         | 自动路由 QA / Analysis / Chunk 的统一入口 | 推荐 Agent 默认使用                                                      |
| `search_qa`                | 直接检索 active QA                        | 返回 evidence 和 paper                                                   |
| `get_paper_qa`             | 获取指定 Paper 的 QA 列表                 | 支持状态、版本、分页                                                     |
| `search_paper_chunks`      | 原文证据检索                              | 可限定 paper / section / direction                                       |
| `get_chunk_context`        | 取某 Chunk 的邻近上下文和结构位置         | 避免 search tool 返回过长文本                                            |
| `get_paper_analysis`       | 获取指定 Paper 的结构化分析               | 可选择 analysis type/version                                             |
| `search_by_direction`      | 面向 taxonomy 浏览与统计                  | 本质是带 direction filter 的 paper search，但提供更清晰 Agent affordance |
| `list_research_directions` | 浏览 taxonomy                             | 返回 hierarchy 和 aliases                                                |
| `get_related_papers`       | citation、semantic、manual relation       | relation type 明确                                                       |
| `get_citations`            | 获取引用与被引关系                        | 支持方向、年份过滤                                                       |
| `get_evidence`             | 根据 evidence ID 获取可引用原文和定位     | 统一 QA / Analysis provenance                                            |

### 14.3 Avoiding overlap

- `search_papers` 返回论文候选，不返回大量原文。
- `search_paper_chunks` 只搜索 Source of Truth content。
- `search_qa` 只搜索已有 QA。
- `search_knowledge` 是 orchestrator，结果必须标注来源类型，不能隐藏它调用了什么。
- `get_*` 接口只按稳定 ID 读取详情，不做模糊搜索。
- `search_by_direction` 可作为便捷领域 Tool；底层复用同一 retrieval service，避免独立实现。

## 14.4 Agent composition examples

### “最近两年 Agent Memory 中关于 episodic memory 的论文”

1. `list_research_directions` resolve direction。
2. `search_papers` with date + direction + keyword/semantic query。
3. 需要结论时，对 top papers 调 `get_paper_analysis`。
4. 需要原文时调 `search_paper_chunks`。

### “论文 X 对长期记忆的主要结论是什么？”

1. `get_paper` resolve Paper。
2. `get_paper_analysis`。
3. `get_paper_qa` 或 `search_qa`。
4. `get_evidence` / `search_paper_chunks` 核验。

### “哪些论文支持或反驳某个观点？”

1. `search_knowledge(mode=auto)` 得到 QA/Analysis/Chunk candidates。
2. 用 direction/date filter 扩大候选。
3. `get_related_papers` / `get_citations` 扩展。
4. Agent 根据 Evidence Bundle 汇总，不让数据库生成新 QA。

---

## 15. Repository Structure

```text
paper-kb/
├── apps/
│   ├── api/
│   ├── mcp/
│   ├── worker/
│   └── admin/
├── paper_kb/
│   ├── domain/
│   │   ├── papers/
│   │   ├── documents/
│   │   ├── taxonomy/
│   │   ├── analysis/
│   │   ├── qa/
│   │   ├── citations/
│   │   └── retrieval/
│   ├── collectors/
│   │   ├── arxiv/
│   │   ├── crossref/
│   │   ├── openalex/
│   │   └── semantic_scholar/
│   ├── parsers/
│   │   ├── adapters/
│   │   ├── normalization/
│   │   └── chunking/
│   ├── pipelines/
│   │   ├── ingestion/
│   │   ├── analysis_import/
│   │   ├── qa_import/
│   │   ├── taxonomy_assignment/
│   │   └── indexing/
│   ├── retrieval/
│   │   ├── planning/
│   │   ├── lexical/
│   │   ├── dense/
│   │   ├── fusion/
│   │   ├── reranking/
│   │   └── evaluation/
│   ├── storage/
│   │   ├── relational/
│   │   ├── artifacts/
│   │   ├── vector/
│   │   └── search/
│   └── observability/
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── pipeline/
│   └── retrieval_eval/
├── docs/
│   ├── architecture/
│   ├── taxonomy/
│   ├── ingestion/
│   ├── qa_import/
│   ├── retrieval/
│   └── operations/
└── deploy/
```

重点：

- 明确使用 `qa_import/`，不出现 `qa_generation/`。
- `analysis_import/` 同样强调本知识库可接收外部派生结果。
- Domain 不依赖具体数据库。
- Search/vector/object storage 都通过 adapter，可在 scale-up 时替换。

---

## 16. MVP Roadmap

## Phase 1 — Reliable Paper KB Foundation

### 核心目标

构建可长期运行、可追溯、可检索的最小闭环。

### 主要组件

- canonical Paper / Author / Source identity
- PDF artifact storage
- 一个主 parser + 一个 fallback parser adapter
- normalized DocumentVersion
- Section / ChunkSet / Chunk
- human-maintained taxonomy + manual assignment
- PaperAnalysis import
- Existing QA import、版本、evidence alignment
- PostgreSQL FTS + pgvector basic retrieval
- MCP：paper、QA、chunk、analysis 基础 tools
- ingestion status、retry、审计和 basic admin

### 技术依赖

- PostgreSQL + pgvector
- S3-compatible object storage
- worker queue
- Docling 或 GROBID / MinerU 之一作为首选 parser

### 为什么先做

所有后续能力依赖稳定 identity、version 和 provenance。Phase 1 的成功标准不是“回答很聪明”，而是数据可重放、可核验、可维护。

## Phase 2 — Retrieval Quality and Operational Scale

### 核心目标

提升召回、排序、QA 管理与自动 ingestion。

### 主要组件

- BM25 + dense + RRF + reranker
- retrieval planner
- QA duplicate candidates、人工 review 和 stale detection
- parser/chunk re-alignment
- citation graph 与 citation context
- automated collectors / scheduled updates
- taxonomy suggestion workflow
- retrieval evaluation dashboard
- 可选 OpenSearch

### 为什么此时做

只有 Phase 1 累积真实语料和查询后，才能测出 BM25、embedding、reranker 和专用搜索系统的价值。

## Phase 3 — Cross-paper Knowledge and Research Intelligence

### 核心目标

支持跨论文综合、知识图谱、趋势和推荐。

### 主要组件

- cross-paper QA / synthesis objects
- entity resolution and domain knowledge graph
- graph + vector retrieval
- trend analysis by direction/topic/time
- recommendation and literature gap discovery
- related-paper learning from user feedback
- 可选 Neo4j / specialized vector DB

### 为什么最后做

这些能力成本高、评估困难，并依赖稳定的 source grounding、citation 和 taxonomy。过早实施会把 parser 和实体消歧错误放大为“知识”。

---

## 17. Risks & Trade-offs

| Risk                    | Impact                    | Mitigation                                                                |
| ----------------------- | ------------------------- | ------------------------------------------------------------------------- |
| PDF parsing errors      | QA/Analysis evidence 错位 | 原 PDF 保留；parser provenance；多 parser；page/span anchor；人工修正     |
| Metadata conflicts      | 去重错误、引用错误        | provider snapshots；canonical merge policy；人工 lock                     |
| Chunk version churn     | 旧 QA evidence 失效       | Evidence 保留稳定定位；ChunkSet version；后台 re-alignment                |
| Taxonomy drift          | 历史统计不可比            | taxonomy version；deprecated/successor；assignment history                |
| Tag explosion           | 筛选噪声                  | alias/synonym；controlled tag promotion；usage review                     |
| QA stale or low quality | Agent 返回错误答案        | active status、quality filter、evidence requirement、superseded exclusion |
| Index inconsistency     | 已删除数据仍可检索        | transactional outbox；reconciliation；索引可重建                          |
| Over-engineering        | 交付慢、运维负担大        | MVP 单主库；用压测和评测触发拆分                                          |
| Embedding model change  | 全量重算成本              | embedding version 共存；active pointer；批量后台迁移                      |
| Graph hallucination     | 错误关系被当事实          | graph edge 必须带 source/provenance；区分 citation 与 inferred relation   |
| Access leakage          | 跨项目暴露未公开论文      | ACL filter 前推；namespace 只用于真实安全边界；MCP 层授权                 |

---

## 18. Final Recommended Architecture

### 18.1 Final decision

采用：

```text
Unified PostgreSQL + pgvector
        +
S3-compatible Object Storage
        +
Asynchronous Ingestion Workers
        +
Canonical Parsed Document Layer
        +
Independent QA / Analysis Entities
        +
Hierarchical Multi-label Taxonomy
        +
Unified Hybrid Retrieval Service
        +
REST / MCP Interface
```

### 18.2 Decisions to defer

在真实数据与查询压测前暂缓：

- OpenSearch
- Qdrant / Milvus / Weaviate
- Neo4j
- 全量知识图谱
- 自动创建 taxonomy node
- cross-paper QA

### 18.3 Architecture decision rules

1. 主数据必须事务一致。
2. 原始 artifact 不可变。
3. 派生知识可版本化、可失效、可追溯。
4. 索引可删除重建。
5. Classification suggestion 与 human-approved taxonomy 分开。
6. QA 是独立实体，并同时是检索对象。
7. Agent 只使用稳定领域工具，不直接访问数据库。
8. 新基础设施必须由评测或压测证明必要。

---

## Appendix A — Suggested Architecture Decision Records

进入实现阶段前建议先写以下 ADR：

1. Canonical Paper Identity and Metadata Merge
2. Artifact Storage and Content Addressing
3. Canonical Parsed Document Representation
4. Section / Chunk Versioning
5. ResearchDirection vs Topic vs Tag vs Collection vs Namespace
6. QA Import, Versioning and Evidence Alignment
7. PostgreSQL FTS + pgvector MVP
8. Retrieval Fusion and Reranking
9. Index Synchronization and Rebuild
10. MCP Tool Boundaries

## Appendix B — Primary References

- Future-House PaperQA: https://github.com/Future-House/paper-qa
- Docling: https://github.com/docling-project/docling
- Paperless-ngx: https://github.com/paperless-ngx/paperless-ngx
- Zotero: https://github.com/zotero/zotero
- S2ORC Doc2JSON: https://github.com/allenai/s2orc-doc2json
- Science Parse: https://github.com/allenai/science-parse
- LlamaIndex: https://github.com/run-llama/llama_index
- Haystack: https://github.com/deepset-ai/haystack
- LightRAG: https://github.com/HKUDS/LightRAG
- Microsoft GraphRAG: https://github.com/microsoft/graphrag
- RAG-Anything: https://github.com/HKUDS/RAG-Anything
- OpenAlex: https://docs.openalex.org/
- Semantic Scholar API: https://www.semanticscholar.org/product/api
- pgvector: https://github.com/pgvector/pgvector
- OpenSearch hybrid search: https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/
- Qdrant hybrid search: https://qdrant.tech/documentation/concepts/hybrid-queries/
- Milvus multi-vector hybrid search: https://milvus.io/docs/multi-vector-search.md