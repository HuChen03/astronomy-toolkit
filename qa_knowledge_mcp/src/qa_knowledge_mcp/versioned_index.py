from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lab_knowledge_platform.knowledge_store import KnowledgeStore
from lab_knowledge_platform.paths import INDEX_ROOT, KNOWLEDGE_OVERLAY_DB, PROJECT_ROOT

from .build_kb import build


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def active_index(index_root: Path = INDEX_ROOT) -> Path | None:
    pointer = index_root / "active.json"
    if not pointer.exists():
        return None
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    version = str(payload.get("index_version") or "")
    candidate = index_root / "versions" / version
    return candidate if version and candidate.exists() else None


def build_versioned_index(
    source: Path,
    *,
    index_root: Path = INDEX_ROOT,
    overlay_db: Path = KNOWLEDGE_OVERLAY_DB,
    embedding: bool = False,
    model_name: str = "",
    device: str = "cpu",
    batch_size: int = 8,
) -> dict[str, Any]:
    source = source if source.is_absolute() else PROJECT_ROOT / source
    index_root = index_root if index_root.is_absolute() else PROJECT_ROOT / index_root
    source_hash = sha256_file(source)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    index_version = f"{timestamp}-{source_hash[:12]}"
    version_dir = index_root / "versions" / index_version
    version_dir.mkdir(parents=True, exist_ok=False)
    count = build(
        source,
        version_dir,
        embedding=embedding,
        model_name=model_name or os.environ.get("QA_EMBEDDING_MODEL", ""),
        device=device,
        batch_size=batch_size,
    )
    manifest_path = version_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "schema_version": 2,
        "index_version": index_version,
        "source_hash": source_hash,
        "built_at": datetime.now(timezone.utc).isoformat(),
    })
    overlay_chunks = []
    if overlay_db.exists():
        overlay_chunks = KnowledgeStore(overlay_db).export_search_chunks()
        (version_dir / "overlay_chunks.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in overlay_chunks), encoding="utf-8"
        )
    manifest["overlay_record_count"] = len(overlay_chunks)
    manifest["overlay_source_types"] = sorted({row["source_type"] for row in overlay_chunks})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validation = {
        "ok": manifest.get("record_count") == count,
        "record_count": count,
        "source_hash": source_hash,
    }
    (version_dir / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not validation["ok"]:
        raise RuntimeError(f"index validation failed for {index_version}")
    index_root.mkdir(parents=True, exist_ok=True)
    pointer = index_root / "active.json"
    temporary = pointer.with_suffix(".tmp")
    temporary.write_text(json.dumps({"index_version": index_version}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(pointer)
    if overlay_db.exists():
        KnowledgeStore(overlay_db).register_index(index_version, source_hash, manifest)
    return {"index_version": index_version, "path": str(version_dir), "manifest": manifest, "validation": validation}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build and atomically publish a versioned QA index.")
    parser.add_argument("source", type=Path, default=PROJECT_ROOT / "data/cosmological_simulation/generate_paper.jsonl", nargs="?")
    parser.add_argument("--index-root", type=Path, default=INDEX_ROOT)
    parser.add_argument("--embedding", action="store_true")
    parser.add_argument("--model", default="")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    result = build_versioned_index(
        args.source,
        index_root=args.index_root,
        embedding=args.embedding,
        model_name=args.model,
        device=args.device,
        batch_size=args.batch_size,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
