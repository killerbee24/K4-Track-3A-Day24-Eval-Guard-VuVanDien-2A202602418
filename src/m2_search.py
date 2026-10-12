from __future__ import annotations

"""Module 2: Vietnamese BM25 + dense Qdrant retrieval + RRF."""

import os
import re
import sys
from dataclasses import dataclass
from functools import lru_cache

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    BM25_TOP_K,
    COLLECTION_NAME,
    DENSE_TOP_K,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    HYBRID_TOP_K,
    QDRANT_HOST,
    QDRANT_PORT,
)


@dataclass
class SearchResult:
    text: str
    score: float
    metadata: dict
    method: str


def segment_vietnamese(text: str) -> str:
    from underthesea import word_tokenize

    return word_tokenize(text, format="text").replace("_", " ") if text.strip() else ""


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", segment_vietnamese(text).lower(), flags=re.UNICODE)


def query_facets(query: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\s+và\s+", query, flags=re.IGNORECASE)]
    return parts if len(parts) > 1 and all(len(part) > 8 for part in parts) else [query]


class BM25Search:
    def __init__(self):
        self.corpus_tokens = []
        self.documents = []
        self.bm25 = None

    def index(self, chunks: list[dict]) -> None:
        from rank_bm25 import BM25Okapi

        self.documents = [c for c in chunks if c["text"].strip()]
        self.corpus_tokens = [_tokens(c["text"]) for c in self.documents]
        self.bm25 = BM25Okapi(self.corpus_tokens) if any(self.corpus_tokens) else None

    def search(self, query: str, top_k: int = BM25_TOP_K) -> list[SearchResult]:
        if self.bm25 is None or top_k <= 0:
            return []
        tokens = _tokens(query)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [
            SearchResult(
                self.documents[i]["text"],
                float(scores[i]),
                dict(self.documents[i].get("metadata", {})),
                "bm25",
            )
            for i in indices[:top_k]
            if scores[i] > 0
        ]


@lru_cache(maxsize=2)
def load_encoder(model_name: str = EMBEDDING_MODEL):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


class DenseSearch:
    def __init__(self, client=None):
        from qdrant_client import QdrantClient

        self.backend = "provided"
        if client is not None:
            self.client = client
        else:
            try:
                self.client = QdrantClient(
                    host=QDRANT_HOST, port=QDRANT_PORT, timeout=5
                )
                self.client.get_collections()
                self.backend = "docker"
            except Exception:  # noqa: BLE001 - Qdrant connection fallback.
                self.client = QdrantClient(":memory:")
                self.backend = "memory"
                print("  Qdrant Docker unavailable; using in-memory Qdrant.")
        self._encoder = None
        self._indexed = set()

    def _get_encoder(self):
        if self._encoder is None:
            self._encoder = load_encoder()
        return self._encoder

    def index(self, chunks: list[dict], collection: str = COLLECTION_NAME) -> None:
        from qdrant_client.models import Distance, PointStruct, VectorParams

        chunks = [c for c in chunks if c["text"].strip()]
        if self.client.collection_exists(collection):
            self.client.delete_collection(collection)
        self.client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        self._indexed.add(collection)
        if not chunks:
            return
        texts = [c["text"] for c in chunks]
        vectors = self._get_encoder().encode(
            texts, normalize_embeddings=True, show_progress_bar=True
        )
        if vectors.shape[1] != EMBEDDING_DIM:
            raise ValueError(
                f"Embedding dimension {vectors.shape[1]} != {EMBEDDING_DIM}"
            )
        for start in range(0, len(chunks), 64):
            points = [
                PointStruct(
                    id=i,
                    vector=vectors[i].tolist(),
                    payload={
                        **chunks[i].get("metadata", {}),
                        "text": chunks[i]["text"],
                    },
                )
                for i in range(start, min(start + 64, len(chunks)))
            ]
            self.client.upsert(collection_name=collection, points=points, wait=True)

    def search(
        self, query: str, top_k: int = DENSE_TOP_K, collection: str = COLLECTION_NAME
    ) -> list[SearchResult]:
        if (
            not query.strip()
            or top_k <= 0
            or not self.client.collection_exists(collection)
        ):
            return []
        if self.client.count(collection_name=collection, exact=True).count == 0:
            return []
        query_vector = (
            self._get_encoder().encode(query, normalize_embeddings=True).tolist()
        )
        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=collection,
                query=query_vector,
                limit=top_k,
                with_payload=True,
            )
            points = response.points
        else:
            # qdrant-client 1.9.x (the lab pin) exposes search(); newer
            # clients renamed the same operation to query_points().
            points = self.client.search(
                collection_name=collection,
                query_vector=query_vector,
                limit=top_k,
                with_payload=True,
            )
        return [
            SearchResult(
                pt.payload.get("text", ""),
                float(pt.score),
                {key: value for key, value in pt.payload.items() if key != "text"},
                "dense",
            )
            for pt in points
            if pt.payload
        ]


def reciprocal_rank_fusion(
    results_list: list[list[SearchResult]], k: int = 60, top_k: int = HYBRID_TOP_K
) -> list[SearchResult]:
    if k < 0:
        raise ValueError("RRF k must be non-negative")
    scores, documents = {}, {}
    for ranked in results_list:
        seen = set()
        for rank, result in enumerate(ranked):
            if result.text in seen:
                continue
            seen.add(result.text)
            scores[result.text] = scores.get(result.text, 0.0) + 1.0 / (k + rank + 1)
            documents.setdefault(result.text, result)
    order = sorted(scores, key=scores.get, reverse=True)[: max(0, top_k)]
    return [
        SearchResult(text, scores[text], dict(documents[text].metadata), "hybrid")
        for text in order
    ]


class HybridSearch:
    def __init__(self):
        self.bm25 = BM25Search()
        self.dense = DenseSearch()
        self.parents = {}
        self.timings = {}

    def index(self, chunks: list[dict]) -> None:
        self.bm25.index(chunks)
        self.dense.index(chunks)

    def search(self, query: str, top_k: int = HYBRID_TOP_K) -> list[SearchResult]:
        import time

        start = time.perf_counter()
        bm25 = self.bm25.search(query, top_k=BM25_TOP_K)
        middle = time.perf_counter()
        dense = self.dense.search(query, top_k=DENSE_TOP_K)
        # Keep historical policies available, but don't mix superseded policies
        # into a query asking about current entitlements.
        historical = re.search(
            r"20\d{2}|\bv\s*1\b|phiên bản\s*1|chính sách cũ", query.lower()
        )
        if not historical:
            bm25 = [r for r in bm25 if r.metadata.get("status") != "superseded"]
            dense = [r for r in dense if r.metadata.get("status") != "superseded"]
        lists = [bm25, dense]
        facets = query_facets(query)
        if len(facets) > 1:
            for facet in facets:
                lexical = self.bm25.search(facet, top_k=BM25_TOP_K)
                semantic = self.dense.search(facet, top_k=DENSE_TOP_K)
                if not historical:
                    lexical = [
                        r for r in lexical if r.metadata.get("status") != "superseded"
                    ]
                    semantic = [
                        r for r in semantic if r.metadata.get("status") != "superseded"
                    ]
                lists.extend([lexical, semantic])
        fused = reciprocal_rank_fusion(lists, top_k=top_k)
        end = time.perf_counter()
        self.timings = {
            "bm25_ms": (middle - start) * 1000,
            "dense_and_fusion_ms": (end - middle) * 1000,
        }
        return fused


if __name__ == "__main__":
    print(segment_vietnamese("Nhân viên được nghỉ phép năm"))
