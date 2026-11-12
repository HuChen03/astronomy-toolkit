# Lab Knowledge Platform

> 面向 Linux 服务器、以文献中台为论文事实源的实验室知识平台。知识库检索和每日论文
> 已拆为两个独立 MCP 服务，原 `qa_knowledge_mcp`、`111` 日报项目和 `test` 知识获取项目
> 仍位于同一仓库，但运行时彼此独立。

当前发布包含源码、配置和测试。要在没有论文语料的环境中试用，按[仓库快速开始](../README.md#天文知识库)加载合成 QA 示例。

## 单仓库结构

```text
src/qa_knowledge_mcp/          # 统一知识检索与 MCP
src/literature_digest_agent/   # 每日文献分类、快照、邮件与独立 MCP
pipelines/knowledge_acquisition/ # 论文筛选、阅读卡和 QA 生成脚本
data/cosmological_simulation/  # 当前生产 QA 语料与索引
data/literature_digest/        # 日报 SQLite 快照
data/knowledge_acquisition/    # 原 test 项目的知识资产和加工结果
config/                        # 统一配置
examples/literature_digest/    # 日报输入输出示例
tests/                         # 全仓库测试
```

详细边界和迁移说明见 `docs/repository-structure.md`。

正式文档：

- 当前 MCP 工具、参数、返回结构和调用方式：`docs/mcp-api.md`
- 当前知识库状态、架构边界和后续实施步骤：`docs/knowledge-base-implementation.md`

当前服务使用 `data/cosmological_simulation/generate_paper.jsonl` 作为主 QA
知识库；小方向知识库通过 `config/knowledge_bases/*.json` 注册，并使用相同的
JSONL 格式。日报 Agent 仍保留在仓库内，但当前 MCP 不注册日报工具。

## MCP 服务

当前 MCP 只提供两个只读知识库工具：

- `list_knowledge_bases()`：列出主知识库和已启用的小方向知识库。
- `search_knowledge(query, knowledge_base_ids, top_k, min_score)`：检索 QA Pair
  及对应原文段落；不传小方向时只查主库，传入小方向时查主库加指定方向。

日报、Evidence Pack、Topic、Decision 和管理类工具暂不注册；旧调用方应迁移到上述两个工具。

### 天文学知识库 MCP

这是当前面向天文学/宇宙学文献 QA 的知识库搜索服务，不负责每日论文发现。

默认使用：

```text
QA source: data/cosmological_simulation/generate_paper.jsonl
QA index:  data/cosmological_simulation/index
MCP:       http://<服务器IP>:8001/mcp
```

启动命令：

```bash
QA_ENABLE_EMBEDDING=false \
QA_ENABLE_RERANKER=false \
python3 -m qa_knowledge_mcp.mcp_server \
  --transport streamable-http \
  --host 0.0.0.0 \
  --port 8001
```

每日论文服务使用独立的 `8002` 端口，见下文。

## 安装

```bash
# 在仓库根目录执行
# 先进入 qa_knowledge_mcp/
uv sync --locked
```

如果环境已安装 `mcp`，也可以直接从源码运行。

## 本地测试查询

```bash
python3 -m qa_knowledge_mcp.query \
  "宇宙学模拟中如何控制二体弛豫？" \
  --source data/cosmological_simulation/generate_paper.jsonl \
  --index data/cosmological_simulation/index
```

## 离线构建索引

生产部署推荐先离线构建索引，避免 MCP 服务启动时重新给全量知识库做
embedding：

```bash
export HF_ENDPOINT=https://hf-mirror.com
python3 -m qa_knowledge_mcp.build_kb \
  data/cosmological_simulation/generate_paper.jsonl \
  --output-dir data/cosmological_simulation/index \
  --model BAAI/bge-small-zh-v1.5 \
  --device cpu \
  --batch-size 8
```

会生成：

- `data/cosmological_simulation/index/chunks.jsonl`：扁平化 QA 记录
- `data/cosmological_simulation/index/embeddings.npy`：离线 embedding 向量
- `data/cosmological_simulation/index/faiss.index`：FAISS 向量索引
- `data/cosmological_simulation/index/manifest.json`：索引元信息

然后启动时指定 `--index data/cosmological_simulation/index`。原始文件有新增或修改后，重新执行构建命令
并重启 MCP 服务即可生效。

如果只想构建扁平化 records，不构建向量索引：

```bash
python3 -m qa_knowledge_mcp.build_kb \
  data/cosmological_simulation/generate_paper.jsonl \
  --output-dir data/cosmological_simulation/index \
  --no-embedding
```

## 对外 MCP 服务

Streamable HTTP 地址为 `http://<服务器IP>:8001/mcp`：

```bash
# 在仓库根目录执行
python3 -m qa_knowledge_mcp.mcp_server \
  --transport streamable-http \
  --host 0.0.0.0 \
  --port 8001 \
  --source data/cosmological_simulation/generate_paper.jsonl \
  --index data/cosmological_simulation/index
```

也可以使用环境变量：

```bash
cp .env.example .env
QA_SOURCE=/absolute/path/to/generate_paper.jsonl \
  python3 -m qa_knowledge_mcp.mcp_server --transport streamable-http
```

暴露的工具只有：

- `list_knowledge_bases()`：列出知识库及 QA/论文数量。
- `search_knowledge(query, knowledge_base_ids, top_k, min_score)`：返回 QA Pair、原文段落和检索分数。

DOI 与 arXiv ID 支持精确查询。自然语言查询分别使用 BM25、TF-IDF 和可选的
FAISS 向量召回，再以倒数排名融合（RRF）合并各路候选。主库与小方向库合用
词项覆盖率重排，并可配置 `QA_RERANK_MODEL` 对合并后的候选调用 CrossEncoder。
向量模型默认使用 `BAAI/bge-small-zh-v1.5`。模型不可用时仍可执行词项检索。
流程参考 [Qdrant 的混合查询](https://qdrant.tech/documentation/search/hybrid-queries/)
和 [OpenSearch 的 RRF](https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/rrf/)。

MCP 返回 `score_components` 用于检查召回来源。综合分用于当前查询排序。已有
`min_score` 阈值可用自己的验证查询重新标定。索引与源文件不匹配时，服务使用源文件
并在列库结果中给出 `index_warning`。只部署索引时可使用同一版本的 `chunks.jsonl`
和 `manifest.json`。覆盖层只为精确匹配的 QA 版本补充证据。

`uv run --locked qa-knowledge-evaluate --cases config/retrieval_eval.json` 输出论文级
Recall@K、MRR、nDCG 和 P95 查询延迟。测试集可以用空的 `paper_keys` 标注无答案问题，
也可以通过 `knowledge_base_ids` 指定跨库评测。

推荐模型配置：

```bash
export HF_ENDPOINT=https://hf-mirror.com  # 如需使用 HuggingFace 镜像
export QA_ENABLE_EMBEDDING=true
export QA_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
export QA_EMBEDDING_DEVICE=cpu
export QA_EMBEDDING_BATCH_SIZE=8
# 可选：更强但更慢的重排器
# export QA_RERANK_MODEL=BAAI/bge-reranker-base
```

### 每日论文 MCP

日报 Agent 作为独立服务运行，不加载天文学知识库代码，默认地址为
`http://<服务器IP>:8002/mcp`。每日论文服务使用 `list_categories`、
`get_daily_digest` 等日报工具；天文学知识库服务不会注册这些工具。

启动和管理：

```bash
./run_literature_digest_mcp.sh
./start_literature_digest_mcp.sh
./status_literature_digest_mcp.sh
./stop_literature_digest_mcp.sh
```

日报默认日期按 `Asia/Shanghai` 的 08:00 截止窗口计算。建议通过反向代理分别配置 HTTPS、认证和访问限制。

## 宇宙学数值模拟核心知识库

已接入独立的宇宙学数值模拟 QA 语料：

- 论文：90 篇
- QA records：2402 条
- 数据：`data/cosmological_simulation/`
- 默认端口：`8001`
- MCP 路径：`/mcp`

启动：

```bash
cd /path/to/astronomy-toolkit/qa_knowledge_mcp
./run_cosmological_mcp.sh
```

等价的显式命令：

```bash
QA_ENABLE_EMBEDDING=false QA_ENABLE_RERANKER=false \
python3 -m qa_knowledge_mcp.mcp_server \
  --transport streamable-http \
  --host 0.0.0.0 \
  --port 8001 \
  --source data/cosmological_simulation/generate_paper.jsonl \
  --index data/cosmological_simulation/index
```

通过 MCP 客户端连接 `http://127.0.0.1:8001/mcp` 并调用 `list_knowledge_bases`。协议握手示例见 [MCP API](docs/mcp-api.md#5-调试请求)。

当前索引使用 `--no-embedding` 构建，检索采用 BM25、TF-IDF 和轻量重排。若服务器具备 GPU，可按上文离线构建索引命令补充 BGE embedding 与 FAISS。

后台常驻管理：

```bash
./start_cosmological_mcp.sh
./status_cosmological_mcp.sh
./stop_cosmological_mcp.sh
# 日志：logs/cosmological_mcp.log
```
