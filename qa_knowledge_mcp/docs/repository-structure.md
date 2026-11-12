# Repository Structure

## 1. Purpose

This repository is now the single home for three previously separate projects. They share a repository,
but the two MCP services are separate runtime applications and separate processes:

1. The QA retrieval and unified MCP service.
2. The literature digest agent previously stored in `workspace/111`.
3. The knowledge acquisition scripts and assets previously stored in `workspace/test`.

Runtime code must not import from or read default data paths under those external workspaces.

## 2. Directory Responsibilities

```text
src/
  lab_knowledge_platform/    Shared knowledge-store paths and contracts
  qa_knowledge_mcp/          Astronomy QA retrieval and MCP API (port 8001)
  literature_digest_agent/  Daily literature processing and MCP API (port 8002)

pipelines/
  knowledge_acquisition/     Offline and model-assisted ingestion scripts

data/
  cosmological_simulation/   Canonical runtime QA source and published index
  literature_digest/         Canonical daily digest SQLite database
  knowledge_acquisition/     Imported historical inputs and generated knowledge assets

config/                      Runtime configuration committed to the repository
examples/                    Safe example inputs and client configuration
tests/                       Unit and integration tests for all runtime packages
docs/                        Architecture, API, migration, and operation documentation
```

## 3. Dependency Direction

```text
pipelines/knowledge_acquisition --> data/cosmological_simulation --> src/qa_knowledge_mcp --> MCP clients

literature hub --> src/literature_digest_agent --> data/literature_digest --> MCP clients
```

- Runtime packages never import pipeline scripts.
- Pipeline scripts may call runtime index builders through public CLI modules.
- The two MCP runtime packages do not import each other.
- Both runtime packages resolve paths from the repository root, not the current shell directory.
- Historical artifacts are data inputs, not Python import paths.

## 4. Migrated Paths

| Previous location | Repository location |
|---|---|
| `workspace/111/literature_digest_agent` | `src/literature_digest_agent` |
| `workspace/111/tests` | `tests/literature_digest_agent` |
| `workspace/111/examples` | `examples/literature_digest` |
| `workspace/111/data/literature_digest.sqlite3` | `data/literature_digest/literature_digest.sqlite3` |
| `workspace/test/*.py` | `pipelines/knowledge_acquisition` |
| `workspace/test/cosmological_*` | `data/knowledge_acquisition/cosmological_*` |
| 历史论文加工目录 | `data/knowledge_acquisition/processed_papers/` |
| `workspace/test/paper_library_1_knowledge` | `data/knowledge_acquisition/paper_library_1_knowledge` |

The original `.git` directories, `.env` secrets, Python caches, scratch directories, and duplicate zip archives were intentionally not imported.

## 5. Development Commands

```bash
python3 -m pip install -e '.[vector,dev]'
pytest -q
python3 -m qa_knowledge_mcp.query "宇宙学模拟如何控制二体弛豫？"
python3 -m literature_digest_agent.daily_job --date 2026-08-06
./run_cosmological_mcp.sh
```

For direct source execution without installation, set `PYTHONPATH=src`.
