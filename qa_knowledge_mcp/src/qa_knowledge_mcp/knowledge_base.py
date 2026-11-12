from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter, OrderedDict, defaultdict
from dataclasses import asdict, dataclass
from functools import lru_cache
from itertools import zip_longest
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
    from sentence_transformers import CrossEncoder, SentenceTransformer
except Exception:
    CrossEncoder = None
    SentenceTransformer = None


_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CJK_RUN_RE = re.compile(r"[\u3400-\u9fff]+")
_PAPER_ID_RE = re.compile(r"10\.\d{4,9}[/_][A-Za-z0-9._;()/+:%-]+|\b\d{4}\.\d{4,5}(?:v\d+)?\b", re.I)
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_EMBEDDING_BATCH_SIZE = 8
RRF_K = 20
QUERY_CACHE_SIZE = 256
EMBEDDING_TEXT_VERSION = "question_answer_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
class SearchCandidate:
    record: Record
    rrf_score: float
    bm25_score: float
    sparse_score: float
    vector_score: float

    def public(self, score: float, rerank_score: float) -> dict[str, Any]:
        result = self.record.public(score)
        result["score_components"] = {
            "bm25": round(float(self.bm25_score), 6),
            "tfidf": round(float(self.sparse_score), 6),
            "vector": round(float(self.vector_score), 6),
            "rrf": round(self.rrf_score, 6),
            "rerank": round(float(rerank_score), 6),
        }
        return result


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u3000", " ").split())


def tokenize(text: str) -> list[str]:
    lowered = normalize_text(text).lower()
    tokens = [item.lower() for item in _WORD_RE.findall(lowered)]
    for run in _CJK_RUN_RE.findall(lowered):
        tokens.extend(run)
        tokens.extend(run[index:index + 2] for index in range(len(run) - 1))
    return tokens


def embedding_text(record: Record) -> str:
    return f"{record.question}\n{record.answer}"


def lexical_text(record: Record) -> str:
    return "\n".join((record.question, record.answer, record.source_paragraph, record.paper_title,
                      record.paper_key, doi_from_paper_key(record.paper_key) or "", record.paper_category))


def paper_identifiers(value: str) -> set[str]:
    identifiers = set()
    for match in _PAPER_ID_RE.finditer(value):
        key = match.group().lower().rstrip(".,;:")
        if key.endswith(")") and key.count(")") > key.count("("):
            key = key[:-1]
        identifiers.add(doi_from_paper_key(key) or key)
    return identifiers


def _paper_aliases(paper_key: str) -> set[str]:
    identifiers = paper_identifiers(paper_key)
    return identifiers | {re.sub(r"v\d+$", "", key) for key in identifiers if "/" not in key}


def _identifier_only(query: str) -> bool:
    value = query.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "https://arxiv.org/abs/", "arxiv:"):
        value = value.removeprefix(prefix)
    return _PAPER_ID_RE.fullmatch(value.strip()) is not None


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


class BM25Index:
    def __init__(self, documents: list[list[str]]) -> None:
        self.document_count = len(documents)
        self.document_lengths = [len(doc) for doc in documents]
        self.avg_document_length = sum(self.document_lengths) / self.document_count if self.document_count else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for index, doc in enumerate(documents):
            for term, frequency in Counter(doc).items():
                self.postings[term].append((index, frequency))

    def get_scores(self, query_tokens: list[str], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
        if self.document_count == 0 or not query_tokens:
            return np.zeros(self.document_count, dtype=float)
        scores = np.zeros(self.document_count, dtype=float)
        query_counts = Counter(query_tokens)
        for term, qf in query_counts.items():
            postings = self.postings.get(term, ())
            df = len(postings)
            if df == 0:
                continue
            idf = math.log(1.0 + (self.document_count - df + 0.5) / (df + 0.5))
            for index, tf in postings:
                doc_len = self.document_lengths[index] or 1
                denom = tf + k1 * (1.0 - b + b * (doc_len / (self.avg_document_length or 1.0)))
                scores[index] += idf * ((tf * (k1 + 1.0)) / denom) * (1.0 + math.log1p(qf))
        return scores


@lru_cache(maxsize=2)
def _embedding_model(name: str, device: str):
    return SentenceTransformer(name, device=device)


@lru_cache(maxsize=2)
def _reranker_model(name: str):
    return CrossEncoder(name)


def _top_scores(scores: np.ndarray, depth: int) -> dict[int, float]:
    eligible = np.flatnonzero(np.isfinite(scores) & (scores > 0))
    if eligible.size > depth:
        cutoff = np.partition(scores[eligible], eligible.size - depth)[-depth]
        above = eligible[scores[eligible] > cutoff]
        tied = eligible[scores[eligible] == cutoff][:depth - above.size]
        eligible = np.concatenate((above, tied))
    order = np.lexsort((eligible, -scores[eligible]))
    return {int(index): float(scores[index]) for index in eligible[order]}


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
        self.faiss_index: Any | None = None
        self.reranker: Any | None = None
        self.reranker_model_name = os.environ.get("QA_RERANK_MODEL", "").strip()
        self.model_error = ""
        self.reranker_error = ""
        self.index_error = ""
        self.index_manifest: dict[str, Any] = {}
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self.reload()

    @staticmethod
    def _resolve_index_dir(index_path: Path | None) -> Path | None:
        if index_path is None:
            return None
        if index_path.suffix:
            return index_path.parent
        return index_path

    def reload(self) -> dict[str, Any]:
        self.index_error = ""
        self.index_manifest = {}
        self.records = self._load_index_records()
        self._build_indices()
        return self.stats()

    def _load_index_records(self) -> list[Record]:
        records_path = self._records_index_path()
        if records_path and records_path.is_file():
            try:
                manifest_path = records_path.with_name("manifest.json")
                manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
                if not isinstance(manifest, dict):
                    raise ValueError("index manifest must be a JSON object")
                digest = hashlib.sha256()
                records = []
                with records_path.open("rb") as handle:
                    for line in handle:
                        digest.update(line)
                        if line.strip():
                            records.append(Record(**json.loads(line)))
                if manifest.get("chunks_hash") and manifest["chunks_hash"] != digest.hexdigest():
                    raise ValueError("chunks hash differs from index manifest")
                if manifest.get("record_count", len(records)) != len(records):
                    raise ValueError("record count differs from index manifest")
                if self.source_path.is_file():
                    if manifest.get("source_hash"):
                        if manifest["source_hash"] != sha256_file(self.source_path):
                            raise ValueError("source hash differs from index manifest")
                    elif not self._matches_source(records):
                        raise ValueError("legacy index records differ from source")
                self.index_manifest = manifest
                return records
            except (OSError, TypeError, ValueError) as exc:
                self.index_error = str(exc)
                if not self.source_path.is_file():
                    raise ValueError(f"unusable index {records_path}: {exc}") from exc
        if not self.source_path.is_file():
            raise FileNotFoundError(f"knowledge source does not exist: {self.source_path}")
        return list(iter_records(self.source_path))

    def _matches_source(self, records: list[Record]) -> bool:
        for indexed, source in zip_longest(records, iter_records(self.source_path)):
            if indexed is None or source is None:
                return False
            indexed_payload, source_payload = indexed.payload(), source.payload()
            del indexed_payload["source_file"], source_payload["source_file"]
            if indexed_payload != source_payload:
                return False
        return True

    def _records_index_path(self) -> Path | None:
        if self.index_path is None:
            return None
        if self.index_path.is_dir():
            return self.index_path / "chunks.jsonl"
        return self.index_path

    def _build_indices(self) -> None:
        self.corpus = [lexical_text(record) for record in self.records]
        self.paper_lookup: dict[str, list[int]] = defaultdict(list)
        for index, record in enumerate(self.records):
            for identifier in _paper_aliases(record.paper_key):
                self.paper_lookup[identifier].append(index)
        tokenized_corpus = [tokenize(text) for text in self.corpus]
        self.bm25_index = BM25Index(tokenized_corpus)

        if any(tokenized_corpus):
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
        self.faiss_index = None
        self.model_error = ""
        if not _env_bool("QA_ENABLE_EMBEDDING", True):
            return False
        if faiss is None or SentenceTransformer is None:
            self.model_error = "sentence-transformers or faiss is not installed"
            return False
        manifest = self.index_manifest
        if self.index_dir is None or not manifest.get("has_faiss_index"):
            return False
        faiss_path = self.index_dir / "faiss.index"
        try:
            model_name = str(manifest.get("embedding_model") or "")
            if model_name != self.embedding_model_name:
                raise ValueError(f"offline embedding model mismatch: {model_name}")
            if manifest.get("embedding_text", EMBEDDING_TEXT_VERSION) != EMBEDDING_TEXT_VERSION:
                raise ValueError("offline embedding text format mismatch")
            if manifest.get("faiss_hash"):
                contents = faiss_path.read_bytes()
                if manifest["faiss_hash"] != hashlib.sha256(contents).hexdigest():
                    raise ValueError("FAISS file hash differs from index manifest")
                index = faiss.deserialize_index(np.frombuffer(contents, dtype=np.uint8))
            else:
                index = faiss.read_index(str(faiss_path))
            if index.ntotal != len(self.records) or index.d != manifest.get("embedding_dim"):
                raise ValueError("FAISS size differs from index manifest")
            self.embedding_model = _embedding_model(self.embedding_model_name, os.environ.get("QA_EMBEDDING_DEVICE", "cpu"))
            self.faiss_index = index
            return True
        except Exception as exc:
            self.embedding_model = None
            self.faiss_index = None
            self.index_error = f"{type(exc).__name__}: {exc}"
            return False

    def _build_embedding_index(self) -> None:
        self.embedding_model = None
        self.faiss_index = None
        self.model_error = ""
        if not self.corpus or not _env_bool("QA_ENABLE_EMBEDDING", True):
            return
        if SentenceTransformer is None or faiss is None:
            self.model_error = "sentence-transformers or faiss is not installed"
            return
        try:
            device = os.environ.get("QA_EMBEDDING_DEVICE", "cpu").strip() or "cpu"
            self.embedding_model = _embedding_model(self.embedding_model_name, device)
            embeddings = self.embedding_model.encode(
                [embedding_text(record) for record in self.records],
                batch_size=int(os.environ.get("QA_EMBEDDING_BATCH_SIZE", str(DEFAULT_EMBEDDING_BATCH_SIZE))),
                show_progress_bar=_env_bool("QA_EMBEDDING_PROGRESS", False),
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
            embeddings = np.asarray(embeddings, dtype="float32")
            self.faiss_index = faiss.IndexFlatIP(embeddings.shape[1])
            self.faiss_index.add(embeddings)
        except Exception as exc:
            self.embedding_model = None
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
            self.reranker = _reranker_model(self.reranker_model_name)
        except Exception as exc:
            self.reranker = None
            self.reranker_error = f"{type(exc).__name__}: {exc}"

    def search(self, query: str, top_k: int = 5, min_score: float = 0.0) -> list[dict[str, Any]]:
        candidates = self.recall(query, top_k)
        return self.rank(query, [("", item) for item in candidates], top_k, min_score)

    def recall(self, query: str, top_k: int) -> list[SearchCandidate]:
        query = normalize_text(query)
        if not query:
            raise ValueError("query must not be empty")
        if not self.records:
            return []
        top_k = max(1, min(int(top_k), 100))
        multiplier = int(os.environ.get("QA_RETRIEVAL_CANDIDATE_MULTIPLIER", "8"))
        depth = max(20, top_k, min(top_k * multiplier, 256))
        exact_indices = {index for identifier in paper_identifiers(query)
                         for index in self.paper_lookup.get(identifier, ())}
        if _identifier_only(query):
            return [SearchCandidate(self.records[index], 0.0, 0.0, 0.0, 0.0)
                    for index in sorted(exact_indices)[:depth]]
        tokens = tokenize(query)
        bm25 = _top_scores(self.bm25_index.get_scores(tokens), depth)
        sparse = self._sparse_top(query, depth)
        vector = self._vector_top(query, depth)
        channels = (bm25, sparse, vector)
        fused: dict[int, float] = defaultdict(float)
        weight = (RRF_K + 1) / max(1, sum(bool(channel) for channel in channels))
        for channel in channels:
            for rank, index in enumerate(channel, start=1):
                fused[index] += weight / (RRF_K + rank)
        for index in exact_indices:
            fused.setdefault(index, 0.0)
        ranked = sorted(fused, key=lambda index: (index not in exact_indices, -fused[index], index))[:depth]
        return [
            SearchCandidate(self.records[index], fused[index], bm25.get(index, 0.0),
                            sparse.get(index, 0.0), vector.get(index, 0.0))
            for index in ranked
        ]

    def rank(
        self, query: str, candidates: list[tuple[str, SearchCandidate]], top_k: int, min_score: float,
        *, corpora: list[BM25Index] | None = None,
    ) -> list[dict[str, Any]]:
        """Use common lexical features and one optional rerank pass across the selected libraries."""
        query = normalize_text(query)
        terms = sorted(set(tokenize(query)))
        indexes = corpora or [self.bm25_index]
        doc_count = sum(index.document_count for index in indexes)
        weights = {
            term: math.log1p((doc_count + 0.5) / (sum(len(index.postings.get(term, ())) for index in indexes) + 0.5))
            for term in terms
        }
        total_weight = sum(weights.values()) or 1
        identifiers = paper_identifiers(query)
        ranked = []
        for library, candidate in candidates:
            record = candidate.record
            candidate_terms = set(tokenize(lexical_text(record)))
            matched_terms = [term for term in terms if term in candidate_terms]
            overlap = len(matched_terms) / max(1, len(terms))
            weighted_overlap = sum(weights[term] for term in matched_terms) / total_weight
            exact = bool(identifiers & _paper_aliases(record.paper_key))
            score = 0.55 * candidate.rrf_score + 0.25 * overlap + 0.20 * weighted_overlap
            ranked.append((library, candidate, exact, score, overlap))

        def rank_key(row):
            library, candidate, exact, score, _ = row
            return (-exact, -score, library, candidate.record.doc_id, candidate.record.pair_id)

        ranked.sort(key=rank_key)
        if self.reranker is not None and ranked:
            depth = max(40, min(int(top_k), 100))
            window = ranked[:depth]
            try:
                predictions = np.asarray(self.reranker.predict(
                    [[query, lexical_text(candidate.record)] for _, candidate, _, _, _ in window]
                ), dtype=float)
                if predictions.shape != (len(window),) or not np.isfinite(predictions).all():
                    raise ValueError("invalid cross-encoder scores")
                if predictions.max() > predictions.min():
                    ranks = np.empty(len(window), dtype=int)
                    ranks[np.argsort(-predictions, kind="stable")] = np.arange(len(window))
                    ranked = [
                        (library, candidate, exact,
                         0.8 * score + 0.2 * (RRF_K + 1) / (RRF_K + 1 + ranks[index]), float(predictions[index]))
                        for index, (library, candidate, exact, score, _) in enumerate(window)
                    ] + [(library, candidate, exact, 0.8 * score, overlap)
                         for library, candidate, exact, score, overlap in ranked[depth:]]
                    ranked.sort(key=rank_key)
            except Exception as exc:
                self.reranker_error = f"{type(exc).__name__}: {exc}"

        results = []
        library_ranks: Counter[str] = Counter()
        limit = max(1, min(int(top_k), 100))
        for library, candidate, exact, score, rerank in ranked:
            score = 1.0 if exact else score
            if score < min_score or score <= 0:
                continue
            result = candidate.public(score, rerank)
            if library:
                library_ranks[library] += 1
                result.update(knowledge_base_id=library, retrieval_rank=library_ranks[library])
            results.append(result)
            if len(results) >= limit:
                break
        return results

    def _sparse_top(self, query: str, depth: int) -> dict[int, float]:
        if self.sparse_matrix is None or self.sparse_vectorizer is None:
            return {}
        query_vector = self.sparse_vectorizer.transform([query])
        scores = query_vector.dot(self.sparse_matrix.T).toarray().ravel()
        return _top_scores(scores, depth)

    def _vector_top(self, query: str, depth: int) -> dict[int, float]:
        if self.faiss_index is None or self.embedding_model is None:
            return {}
        query_embedding = self._query_embedding(query)
        if query_embedding is None or query_embedding.shape != (1, self.faiss_index.d):
            return {}
        scores, indices = self.faiss_index.search(query_embedding, min(depth, self.faiss_index.ntotal))
        minimum = float(os.environ.get("QA_VECTOR_MIN_SIMILARITY", "0.25"))
        return {int(index): float(score) for score, index in zip(scores[0], indices[0])
                if index >= 0 and np.isfinite(score) and score >= minimum}

    def _query_embedding(self, query: str) -> np.ndarray | None:
        cached = self._cache.get(query)
        if cached is not None:
            self._cache.move_to_end(query)
            return cached
        try:
            embedding = self.embedding_model.encode([query], show_progress_bar=False, normalize_embeddings=True)
            vector = np.asarray(embedding, dtype="float32")
        except Exception as exc:
            self.model_error = f"{type(exc).__name__}: {exc}"
            return None
        self._cache[query] = vector
        if len(self._cache) > QUERY_CACHE_SIZE:
            self._cache.popitem(last=False)
        return vector

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
            "bm25_backend": "inverted_bm25",
            "embedding_model": self.embedding_model_name if self.embedding_model is not None else None,
            "reranker_model": self.reranker_model_name if self.reranker is not None else None,
            "has_bm25_index": self.bm25_index is not None,
            "has_sparse_index": self.sparse_matrix is not None,
            "has_faiss_index": self.faiss_index is not None,
            "index_error": self.index_error,
            "model_error": self.model_error,
            "reranker_error": self.reranker_error,
        }
