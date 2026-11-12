# Astronomy Knowledge Bases

本目录配置的是天文学/宇宙学知识库。主 MCP 是天文学知识库搜索服务，不负责每日论文发现。
每个小方向知识库使用与主知识库相同的 JSONL 格式：每行一个论文对象，`result.qa_pairs` 中包含 `question`、`answer`，可选 `source_paragraph`、`source_section`、`source_page_start` 和 `source_page_end`。

新增方向时复制一个 JSON 配置，例如：

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

调用 `search_knowledge` 时传入 `knowledge_base_ids: ["radiative_transfer"]`，实际检索范围为 `main + radiative_transfer`。不传时只检索 `main`。
