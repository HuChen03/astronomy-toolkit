# Astronomy Toolkit

| 项目 | 用途 |
| --- | --- |
| [天文学知识库](qa_knowledge_mcp/) | 天文与宇宙学论文 QA 检索、索引构建、知识加工脚本及独立的每日文献 MCP。 |
| [Cosmo Agent](cosmo-agent/) | 通过 `cosmo-exec` MCP 调用 GADGET-4、Arepo、HBT+ 和 2LPTIC，配套 Agent Skills、模拟参数、运行脚本与测试。 |

两套项目各有依赖和锁文件。下面的命令从克隆后的仓库根目录执行，需要 Python 3.12 和 uv。

## 天文知识库

```bash
cd qa_knowledge_mcp
uv sync --locked --extra dev
QA_ENABLE_EMBEDDING=false QA_ENABLE_RERANKER=false \
  uv run --locked qa-knowledge-query '引力软化有什么作用？' \
  --source examples/astronomy_qa/demo.jsonl
QA_ENABLE_EMBEDDING=false QA_ENABLE_RERANKER=false \
  uv run --locked astronomy-knowledge-mcp \
  --source examples/astronomy_qa/demo.jsonl \
  --transport streamable-http --host 127.0.0.1 --port 8001
```

MCP 客户端可连接 `http://127.0.0.1:8001/mcp`，使用 `list_knowledge_bases` 和 `search_knowledge`。示例是合成 QA。使用实际语料时，可挂载自己的 `generate_paper.jsonl`，用 `--source` 指定文件，用 `--index` 指定对应的可选索引。论文语料、生产索引和数据库保存在 Inspire。子库配置和日报启动方式见[知识库说明](qa_knowledge_mcp/README.md)。

## 宇宙学模拟 MCP

```bash
cd cosmo-agent
uv sync --project mcp_server --locked
uv run --project mcp_server --locked python scripts/mcp_cli.py --list-tools
uv run --project mcp_server --locked cosmo-exec-mcp --env environments/local.yaml
```

`cosmo-exec-mcp` 默认使用 stdio，由 MCP 客户端拉起。随附环境清单以 `cosmo-agent/` 为工作目录。运行原生模拟需要在执行主机准备相应软件和 MPI，并填写该主机的环境清单。构建参考和客户端配置见 [Cosmo Agent 安装说明](cosmo-agent/docs/install_and_client.md)。

## 测试

在 `qa_knowledge_mcp/` 运行 `uv run --locked --extra dev pytest -q`。在 `cosmo-agent/` 运行下面的命令。

```bash
uv run --project mcp_server --locked --extra simulation python -m unittest discover -s mcp_server/tests -p 'test_*.py'
uv run --project mcp_server --locked python mcp_server/tests/smoke_client.py
uv run --project mcp_server --locked python scripts/check_skills.py
```
