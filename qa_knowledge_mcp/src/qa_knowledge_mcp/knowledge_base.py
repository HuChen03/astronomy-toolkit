from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .paths import PROJECT_ROOT

try:
    import faiss
except Exception:
    faiss = None

try:
    from rank_bm25 import BM25Okapi
except Exception:
    BM25Okapi = None

try:
    from sentence_transformers import CrossEncoder, SentenceTransformer
except Exception:
    CrossEncoder = None
    SentenceTransformer = None


_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_EMBEDDING_BATCH_SIZE = 8


@dataclass(frozen=True)
class Record:
    doc_id: str
    pair_id: int
    question: str
    answer: str
    source_file: str
    source_line: int
    status: str = "done"
    paper_key: str = ""
    paper_title: str = ""
    paper_category: str = ""
    paper_source: str = ""
    paper_rank: int | None = None
    source_paragraph: str = ""
    source_section: str = ""
    source_page_start: int | None = None
    source_page_end: int | None = None

    def payload(self) -> dict[str, Any]:
        return asdict(self)

    def public(self, score: float | None = None) -> dict[str, Any]:
        result = self.payload()
        result.pop("source_file", None)
        result.pop("paper_source", None)
        if score is not None:
            result["score"] = round(float(score), 6)
        return result


@dataclass(frozen=True)
class SearchResult:
    record: Record
    score: float
    bm25_score: float
    vector_score: float
    rerank_score: float

    def public(self) -> dict[str, Any]:
        result = self.record.public(self.score)
        result["score_components"] = {
            "bm25": round(float(self.bm25_score), 6),
            "vector": round(float(self.vector_score), 6),
            "rerank": round(float(self.rerank_score), 6),
        }
        return result


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u3000", " ").split())


def tokenize(text: str) -> list[str]:
    lowered = normalize_text(text).lower()
    tokens = [item.lower() for item in _WORD_RE.findall(lowered)]
    cjk = _CJK_RE.findall(lowered)
    tokens.extend(cjk)
    tokens.extend("".join(cjk[index : index + 2]) for index in range(len(cjk) - 1))
    return tokens


def _stable_doc_id(row: dict[str, Any]) -> str:
    supplied = normalize_text(row.get("hash"))
    if supplied:
        return supplied
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def doi_from_paper_key(value: str) -> str | None:
    key = normalize_text(value)
    if not re.match(r"^10\.\d{4,9}_", key, re.IGNORECASE):
        return None
    prefix, suffix = key.split("_", 1)
    return f"{prefix}/{suffix}"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def resolve_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([Path.cwd() / path, PROJECT_ROOT / path])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return path


def iter_records(path: Path) -> Iterable[Record]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            doc_id = _stable_doc_id(row)
            metadata = row.get("metadata") or {}
            pairs = ((row.get("result") or {}).get("qa_pairs") or [])
            for pair_id, pair in enumerate(pairs):
                question = normalize_text(pair.get("question"))
                answer = normalize_text(pair.get("answer"))
                if question or answer:
                    yield Record(
                        doc_id=doc_id,
                        pair_id=pair_id,
                        question=question,
                        answer=answer,
                        source_file=str(path),
                        source_line=line_number,
                        paper_key=normalize_text(metadata.get("key")),
                        paper_title=normalize_text(metadata.get("title")),
                        paper_category=normalize_text(metadata.get("category")),
                        paper_source=normalize_text(metadata.get("source")),
                        paper_rank=int(metadata["rank"]) if metadata.get("rank") is not None else None,
                        source_paragraph=normalize_text(pair.get("source_paragraph")),
                        source_section=normalize_text(pair.get("source_section")),
                        source_page_start=pair.get("source_page_start"),
                        source_page_end=pair.get("source_page_end"),
                    )


class FallbackBM25Index:
    def __init__(self, documents: list[list[str]]) -> None:
        self.documents = documents
        self.document_count = len(documents)
        self.document_lengths = [len(doc) for doc in documents]
        self.avg_document_length = sum(self.document_lengths) / self.document_count if self.document_count else 0.0
        self.term_frequencies = [Counter(doc) for doc in documents]
        self.document_frequencies: dict[str, int] = defaultdict(int)
        for doc in documents:
            for term in set(doc):
                self.document_frequencies[term] += 1

    def get_scores(self, query_tokens: list[str], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
        if self.document_count == 0 or not query_tokens:
            return np.zeros(self.document_count, dtype=float)
        scores = np.zeros(self.document_count, dtype=float)
        query_counts = Counter(query_tokens)
        for term, qf in query_counts.items():
            df = self.document_frequencies.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1.0 + (self.document_count - df + 0.5) / (df + 0.5))
            for index, tf_counts in enumerate(self.term_frequencies):
                tf = tf_counts.get(term, 0)
                if tf == 0:
                    continue
                doc_len = self.document_lengths[index] or 1
                denom = tf + k1 * (1.0 - b + b * (doc_len / (self.avg_document_length or 1.0)))
                scores[index] += idf * ((tf * (k1 + 1.0)) / denom) * (1.0 + math.log1p(qf))
        return scores


class KnowledgeBase:
    def __init__(self, source_path: Path, index_path: Path | None = None) -> None:
        self.source_path = resolve_path(source_path) or source_path
        self.index_path = resolve_path(index_path)
        self.index_dir = self._resolve_index_dir(self.index_path)
        self.records: list[Record] = []
        self.corpus: list[str] = []
        self.bm25_index: Any | None = None
        self.sparse_vectorizer: TfidfVectorizer | None = None
        self.sparse_matrix = None
        self.embedding_model: Any | None = None
        self.embedding_model_name = os.environ.get("QA_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        self.embeddings: np.ndarray | None = None
        self.faiss_index: Any | None = None
        self.reranker: Any | None = None
        self.reranker_model_name = os.environ.get("QA_RERANK_MODEL", "").strip()
        self.model_error = ""
        self.reranker_error = ""
        self._cache: dict[str, np.ndarray] = {}
        self.reload()

    @staticmethod
    def _resolve_index_dir(index_path: Path | None) -> Path | None:
        if index_path is None:
            return None
        if index_path.suffix:
            return index_path.parent
        return index_path

    def reload(self) -> dict[str, Any]:
        records_path = self._records_index_path()
        if records_path and records_path.exists():
            self.records = [self._load_record(json.loads(line)) for line in records_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        elif self.source_path.exists():
            self.records = list(iter_records(self.source_path))
        else:
            raise FileNotFoundError(f"knowledge source does not exist: {self.source_path}")
        self._build_indices()
        return self.stats()

    def _records_index_path(self) -> Path | None:
        if self.index_path is None:
            return None
        if self.index_path.is_dir():
            return self.index_path / "chunks.jsonl"
        return self.index_path

    @staticmethod
    def _load_record(payload: dict[str, Any]) -> Record:
        return Record(**dict(payload))

    def _build_indices(self) -> None:
        self.corpus = [f"{record.question}\n{record.answer}\n{record.source_paragraph}" for record in self.records]
        tokenized_corpus = [tokenize(text) for text in self.corpus]
        self.bm25_index = BM25Okapi(tokenized_corpus) if BM25Okapi is not None else FallbackBM25Index(tokenized_corpus)

        if self.corpus:
            self.sparse_vectorizer = TfidfVectorizer(
                tokenizer=tokenize,
                preprocessor=normalize_text,
                token_pattern=None,
                ngram_range=(1, 2),
                min_df=1,
                norm="l2",
                sublinear_tf=True,
            )
            self.sparse_matrix = self.sparse_vectorizer.fit_transform(self.corpus)
        else:
            self.sparse_vectorizer = None
            self.sparse_matrix = None

        if not self._load_embedding_index():
            self._build_embedding_index()
        self._build_reranker()
        self._cache.clear()

    def _load_embedding_index(self) -> bool:
        self.embedding_model = None
        self.embeddings = None
        self.faiss_index = None
        self.model_error = ""
        if not _env_bool("QA_ENABLE_EMBEDDING", True):
            return False
        if faiss is None or SentenceTransformer is None:
            self.model_error = "sentence-transformers or faiss is not installed"
            return False
        if self.index_dir is None:
            return False
        faiss_path = self.index_dir / "faiss.index"
        embeddings_path = self.index_dir / "embeddings.npy"
        manifest_path = self.index_dir / "manifest.json"
        if not faiss_path.exists() or not embeddings_path.exists() or not manifest_path.exists():
            return False
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("record_count") != len(self.records):
                self.model_error = "offline embedding index record_count does not match records"
                return False
            model_name = str(manifest.get("embedding_model") or "")
            if model_name and model_name != self.embedding_model_name:
                self.model_error = f"offline embedding model mismatch: {model_name}"
                return False
            self.embedding_model = SentenceTransformer(self.embedding_model_name, device=os.environ.get("QA_EMBEDDING_DEVICE", "cpu"))
            self.embeddings = np.load(embeddings_path).astype("float32")
            self.faiss_index = faiss.read_index(str(faiss_path))
            return True
        except Exception as exc:
            self.embedding_model = None
            self.embeddings = None
            self.faiss_index = None
            self.model_error = f"{type(exc).__name__}: {exc}"
            return False

    def _build_embedding_index(self) -> None:
        self.embedding_model = None
        self.embeddings = None
        self.faiss_index = None
        self.model_error = ""
        if not self.corpus or not _env_bool("QA_ENABLE_EMBEDDING", True):
            return
        if SentenceTransformer is None or faiss is None:
            self.model_error = "sentence-transformers or faiss is not installed"
            return
        try:
            model_kwargs: dict[str, Any] = {}
            device = os.environ.get("QA_EMBEDDING_DEVICE", "cpu").strip()
            if device:
                model_kwargs["device"] = device
            self.embedding_model = SentenceTransformer(self.embedding_model_name, **model_kwargs)
            embeddings = self.embedding_model.encode(
                self.corpus,
                batch_size=int(os.environ.get("QA_EMBEDDING_BATCH_SIZE", str(DEFAULT_EMBEDDING_BATCH_SIZE))),
                show_progress_bar=_env_bool("QA_EMBEDDING_PROGRESS", False),
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
            self.embeddings = np.asarray(embeddings, dtype="float32")
            self.faiss_index = faiss.IndexFlatIP(self.embeddings.shape[1])
            self.faiss_index.add(self.embeddings)
        except Exception as exc:
            self.embedding_model = None
            self.embeddings = None
            self.faiss_index = None
            self.model_error = f"{type(exc).__name__}: {exc}"

    def _build_reranker(self) -> None:
        self.reranker = None
        self.reranker_error = ""
        if not self.reranker_model_name or not _env_bool("QA_ENABLE_RERANKER", True):
            return
        if CrossEncoder is None:
            self.reranker_error = "sentence-transformers CrossEncoder is not installed"
            return
        try:
            self.reranker = CrossEncoder(self.reranker_model_name)
        except Exception as exc:
            self.reranker = None
            self.reranker_error = f"{type(exc).__name__}: {exc}"

    def search(self, query: str, top_k: int = 5, min_score: float = 0.0) -> list[dict[str, Any]]:
        if not normalize_text(query):
            raise ValueError("query must not be empty")
        if not self.records:
            return []
        top_k = max(1, min(int(top_k), 100))
        candidate_k = max(top_k * int(os.environ.get("QA_RETRIEVAL_CANDIDATE_MULTIPLIER", "8")), top_k, 20)
        query_text = normalize_text(query)

        bm25_scores = self._bm25_scores(query_text)
        sparse_scores = self._sparse_scores(query_text)
        vector_scores = self._vector_scores(query_text)

        candidate_indices = self._candidate_indices([bm25_scores, sparse_scores, vector_scores], candidate_k)
        rerank_scores = self._rerank_scores(query_text, candidate_indices)

        bm25_norm = self._normalize_scores(bm25_scores)
        sparse_norm = self._normalize_scores(sparse_scores)
        vector_norm = self._normalize_scores(vector_scores)
        rerank_norm = self._normalize_scores(rerank_scores)

        results: list[SearchResult] = []
        for index in candidate_indices:
            final_score = (
                0.35 * bm25_norm[index]
                + 0.15 * sparse_norm[index]
                + 0.35 * vector_norm[index]
                + 0.15 * rerank_norm[index]
            )
            if final_score >= min_score and final_score > 0:
                results.append(
                    SearchResult(
                        record=self.records[index],
                        score=final_score,
                        bm25_score=float(bm25_scores[index]),
                        vector_score=float(vector_scores[index]),
                        rerank_score=float(rerank_scores[index]),
                    )
                )
        results.sort(key=lambda item: (item.score, item.record.doc_id, item.record.pair_id), reverse=True)
        return [result.public() for result in results[:top_k]]

    def _bm25_scores(self, query: str) -> np.ndarray:
        if self.bm25_index is None:
            return np.zeros(len(self.records), dtype=float)
        return np.asarray(self.bm25_index.get_scores(tokenize(query)), dtype=float)

    def _sparse_scores(self, query: str) -> np.ndarray:
        if self.sparse_matrix is None or self.sparse_vectorizer is None:
            return np.zeros(len(self.records), dtype=float)
        query_vector = self.sparse_vectorizer.transform([query])
        return query_vector.dot(self.sparse_matrix.T).toarray().ravel()

    def _vector_scores(self, query: str) -> np.ndarray:
        if self.faiss_index is None or self.embedding_model is None:
            return np.zeros(len(self.records), dtype=float)
        query_embedding = self._query_embedding(query)
        if query_embedding is None:
            return np.zeros(len(self.records), dtype=float)
        scores = np.zeros(len(self.records), dtype=float)
        raw_scores, raw_indices = self.faiss_index.search(query_embedding, len(self.records))
        for score, index in zip(raw_scores[0], raw_indices[0]):
            if index >= 0:
                scores[index] = float(score)
        return scores

    def _query_embedding(self, query: str) -> np.ndarray | None:
        cached = self._cache.get(query)
        if cached is not None:
            return cached
        try:
            embedding = self.embedding_model.encode([query], show_progress_bar=False, normalize_embeddings=True)
            vector = np.asarray(embedding, dtype="float32")
        except Exception:
            return None
        self._cache[query] = vector
        return vector

    @staticmethod
    def _candidate_indices(score_arrays: list[np.ndarray], candidate_k: int) -> list[int]:
        selected: set[int] = set()
        for scores in score_arrays:
            if scores.size == 0:
                continue
            limit = min(candidate_k, scores.size)
            ranked = np.argsort(scores)[-limit:]
            selected.update(int(index) for index in ranked if scores[index] > 0)
        if selected:
            return sorted(selected)
        return list(range(min(candidate_k, score_arrays[0].size if score_arrays else 0)))

    def _rerank_scores(self, query: str, candidate_indices: list[int]) -> np.ndarray:
        scores = np.zeros(len(self.records), dtype=float)
        if not candidate_indices:
            return scores
        if self.reranker is not None:
            pairs = [[query, self.corpus[index]] for index in candidate_indices]
            try:
                predictions = self.reranker.predict(pairs)
                for index, score in zip(candidate_indices, predictions):
                    scores[index] = float(score)
                return scores
            except Exception as exc:
                self.reranker_error = f"{type(exc).__name__}: {exc}"
        for index in candidate_indices:
            scores[index] = self._lightweight_rerank(query, self.records[index])
        return scores

    @staticmethod
    def _lightweight_rerank(query: str, record: Record) -> float:
        query_tokens = set(tokenize(query))
        question_tokens = set(tokenize(record.question))
        answer_tokens = set(tokenize(record.answer))
        overlap = len(query_tokens & (question_tokens | answer_tokens))
        phrase_bonus = 3.0 if normalize_text(query).lower() in record.question.lower() else 0.0
        answer_bonus = 1.5 * len(query_tokens & answer_tokens)
        return float(overlap + phrase_bonus + answer_bonus)

    @staticmethod
    def _normalize_scores(scores: np.ndarray) -> np.ndarray:
        if scores.size == 0:
            return scores
        finite_scores = np.nan_to_num(scores.astype(float), nan=0.0, posinf=0.0, neginf=0.0)
        min_score = float(finite_scores.min())
        max_score = float(finite_scores.max())
        if max_score <= min_score:
            if max_score > 0:
                return np.where(finite_scores > 0, 1.0, 0.0)
            return np.zeros_like(finite_scores, dtype=float)
        return (finite_scores - min_score) / (max_score - min_score)

    def get(self, doc_id: str, pair_id: int) -> dict[str, Any] | None:
        for record in self.records:
            if record.doc_id == doc_id and record.pair_id == pair_id:
                return record.public()
        return None

    def evidence_pack(
        self,
        query: str,
        *,
        top_k: int = 8,
        max_per_paper: int = 3,
        min_score: float = 0.0,
    ) -> dict[str, Any]:
        """Return ranked, paper-aware evidence without generating a new answer."""
        top_k = max(1, min(int(top_k), 50))
        max_per_paper = max(1, min(int(max_per_paper), 10))
        candidates = self.search(
            query,
            top_k=min(100, max(top_k * 4, top_k)),
            min_score=min_score,
        )
        selected: list[dict[str, Any]] = []
        per_paper: Counter[str] = Counter()
        paper_order: list[str] = []
        papers: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            paper_identity = candidate.get("paper_key") or candidate["doc_id"]
            if per_paper[paper_identity] >= max_per_paper:
                continue
            per_paper[paper_identity] += 1
            evidence_id = f"{candidate['doc_id']}:{candidate['pair_id']}"
            evidence = {
                "evidence_id": evidence_id,
                "paper_id": candidate["doc_id"],
                "paper_key": candidate.get("paper_key") or None,
                "doi": doi_from_paper_key(candidate.get("paper_key") or ""),
                "paper_title": candidate.get("paper_title") or None,
                "paper_category": candidate.get("paper_category") or None,
                "question": candidate["question"],
                "evidence_text": candidate["answer"],
                "score": candidate["score"],
                "score_components": candidate["score_components"],
                "source": {
                    "source_line": candidate["source_line"],
                    "pair_id": candidate["pair_id"],
                    "locator_quality": "qa_pair",
                },
            }
            selected.append(evidence)
            if paper_identity not in papers:
                paper_order.append(paper_identity)
                papers[paper_identity] = {
                    "paper_id": candidate["doc_id"],
                    "paper_key": candidate.get("paper_key") or None,
                    "doi": doi_from_paper_key(candidate.get("paper_key") or ""),
                    "title": candidate.get("paper_title") or None,
                    "category": candidate.get("paper_category") or None,
                    "rank": candidate.get("paper_rank"),
                    "evidence_ids": [],
                }
            papers[paper_identity]["evidence_ids"].append(evidence_id)
            if len(selected) >= top_k:
                break
        return {
            "query": normalize_text(query),
            "matched": bool(selected),
            "evidence_count": len(selected),
            "paper_count": len(papers),
            "evidence": selected,
            "papers": [papers[identity] for identity in paper_order],
            "provenance": {
                "source_type": "qa_jsonl",
                "retrieval": "hybrid_bm25_tfidf_vector_rerank",
                "generated_answer": False,
            },
        }

    def stats(self) -> dict[str, Any]:
        return {
            "source_name": self.source_path.name,
            "record_count": len(self.records),
            "doc_count": len({record.doc_id for record in self.records}),
            "bm25_backend": "rank_bm25" if BM25Okapi is not None else "fallback",
            "embedding_model": self.embedding_model_name if self.embedding_model is not None else None,
            "reranker_model": self.reranker_model_name if self.reranker is not None else None,
            "has_bm25_index": self.bm25_index is not None,
            "has_sparse_index": self.sparse_matrix is not None,
            "has_faiss_index": self.faiss_index is not None,
            "model_error": self.model_error,
            "reranker_error": self.reranker_error,
        }
