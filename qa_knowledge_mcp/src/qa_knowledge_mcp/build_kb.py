from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np

from .knowledge_base import DEFAULT_EMBEDDING_MODEL, EMBEDDING_TEXT_VERSION, embedding_text, iter_records, sha256_file
from .paths import COSMOLOGICAL_DATA_ROOT

try:
    import faiss
except Exception:
    faiss = None

try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None


def build_records(input_path: Path, output_dir: Path) -> list[Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = list(iter_records(input_path))
    chunks_path = output_dir / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.payload(), ensure_ascii=False) + "\n")
    return records


def build_embeddings(records: list[Any], output_dir: Path, model_name: str, device: str, batch_size: int) -> dict[str, Any]:
    if not records:
        return {"has_faiss_index": False, "embedding_model": model_name, "embedding_dim": 0}
    if SentenceTransformer is None or faiss is None:
        raise RuntimeError("sentence-transformers and faiss-cpu are required to build the offline vector index")

    corpus = [embedding_text(record) for record in records]
    model = SentenceTransformer(model_name, device=device)
    embeddings = model.encode(
        corpus,
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype("float32")

    np.save(output_dir / "embeddings.npy", embeddings)
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    faiss.write_index(index, str(output_dir / "faiss.index"))
    return {
        "has_faiss_index": True,
        "embedding_model": model_name,
        "embedding_dim": int(embeddings.shape[1]),
        "embedding_text": EMBEDDING_TEXT_VERSION,
        "faiss_hash": sha256_file(output_dir / "faiss.index"),
    }


def write_manifest(input_path: Path, output_dir: Path, records: list[Any], embedding_info: dict[str, Any], source_hash: str) -> None:
    manifest = {
        "source_file": str(input_path),
        "source_hash": source_hash,
        "chunks_hash": sha256_file(output_dir / "chunks.jsonl"),
        "record_count": len(records),
        "doc_count": len({record.doc_id for record in records}),
        **embedding_info,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build(input_path: Path, output_dir: Path, *, embedding: bool, model_name: str, device: str, batch_size: int) -> int:
    source_hash = sha256_file(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".qa-build-", dir=output_dir) as temporary:
        stage = Path(temporary)
        records = build_records(input_path, stage)
        embedding_info = {"has_faiss_index": False, "embedding_model": None, "embedding_dim": 0}
        if embedding:
            embedding_info = build_embeddings(records, stage, model_name, device, batch_size)
        if sha256_file(input_path) != source_hash:
            raise RuntimeError(f"knowledge source changed while indexing: {input_path}")
        write_manifest(input_path, stage, records, embedding_info, source_hash)
        for name in ("chunks.jsonl", "embeddings.npy", "faiss.index", "manifest.json"):
            artifact = stage / name
            if artifact.is_file():
                artifact.replace(output_dir / name)
    return len(records)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an offline QA retrieval index from JSONL.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=COSMOLOGICAL_DATA_ROOT / "index")
    parser.add_argument("--no-embedding", action="store_true", help="Only write normalized chunks.jsonl")
    parser.add_argument("--model", default=os.environ.get("QA_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL))
    parser.add_argument("--device", default=os.environ.get("QA_EMBEDDING_DEVICE", "cpu"))
    parser.add_argument("--batch-size", type=int, default=int(os.environ.get("QA_EMBEDDING_BATCH_SIZE", "8")))
    args = parser.parse_args()
    count = build(
        args.input,
        args.output_dir,
        embedding=not args.no_embedding,
        model_name=args.model,
        device=args.device,
        batch_size=args.batch_size,
    )
    print(f"wrote {count} records to {args.output_dir / 'chunks.jsonl'}")
    if not args.no_embedding:
        print(f"wrote FAISS index to {args.output_dir / 'faiss.index'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
