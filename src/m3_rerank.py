from __future__ import annotations

"""Module 3: Reranking — Cross-encoder top-20 → top-3 + latency benchmark."""

import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
from dataclasses import dataclass
from functools import lru_cache

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RERANK_TOP_K


@lru_cache(maxsize=2)
def _cross_encoder(model_name):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)


@dataclass
class RerankResult:
    text: str
    original_score: float
    rerank_score: float
    metadata: dict
    rank: int


class CrossEncoderReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self.model_name = model_name
        self._model = None

    def _load_model(self):
        if self._model is None:
            self._model = _cross_encoder(self.model_name)
        return self._model

    def rerank(
        self, query: str, documents: list[dict], top_k: int = RERANK_TOP_K
    ) -> list[RerankResult]:
        """Rerank documents: top-20 → top-k."""
        if not documents or top_k <= 0:
            return []
        import numpy as np

        pairs = [(query, doc["text"]) for doc in documents]
        scores = np.asarray(self._load_model().predict(pairs)).reshape(-1)
        if len(scores) != len(documents):
            raise ValueError(
                "Reranker returned a different number of scores than documents"
            )
        ordered = sorted(
            zip(scores, documents), key=lambda item: float(item[0]), reverse=True
        )
        return [
            RerankResult(
                doc["text"],
                float(doc.get("score", 0.0)),
                float(score),
                dict(doc.get("metadata", {})),
                i + 1,
            )
            for i, (score, doc) in enumerate(ordered[:top_k])
        ]


class FlashrankReranker:
    """Optional lightweight ONNX reranker; latency depends on hardware."""

    def __init__(self):
        self._model = None

    def rerank(
        self, query: str, documents: list[dict], top_k: int = RERANK_TOP_K
    ) -> list[RerankResult]:
        if not documents or top_k <= 0:
            return []
        from flashrank import Ranker, RerankRequest

        if self._model is None:
            self._model = Ranker()
        passages = [{"id": i, "text": d["text"]} for i, d in enumerate(documents)]
        results = self._model.rerank(RerankRequest(query=query, passages=passages))
        ordered = sorted(results, key=lambda r: r["score"], reverse=True)[:top_k]
        return [
            RerankResult(
                r["text"],
                float(documents[r["id"]].get("score", 0.0)),
                float(r["score"]),
                dict(documents[r["id"]].get("metadata", {})),
                i + 1,
            )
            for i, r in enumerate(ordered)
        ]


def benchmark_reranker(
    reranker, query: str, documents: list[dict], n_runs: int = 5
) -> dict:
    """Benchmark latency over n_runs. (Đã implement sẵn)"""
    times = []
    if n_runs <= 0:
        raise ValueError("n_runs must be positive")
    reranker.rerank(query, documents)  # Warm up; exclude model download/load.
    for _ in range(n_runs):
        start = time.perf_counter()
        reranker.rerank(query, documents)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
    return {
        "avg_ms": sum(times) / len(times),
        "min_ms": min(times),
        "max_ms": max(times),
    }


if __name__ == "__main__":
    query = "Nhân viên được nghỉ phép bao nhiêu ngày?"
    docs = [
        {"text": "Nhân viên được nghỉ 12 ngày/năm.", "score": 0.8, "metadata": {}},
        {"text": "Mật khẩu thay đổi mỗi 90 ngày.", "score": 0.7, "metadata": {}},
        {"text": "Thời gian thử việc là 60 ngày.", "score": 0.75, "metadata": {}},
    ]
    reranker = CrossEncoderReranker()
    for r in reranker.rerank(query, docs):
        print(f"[{r.rank}] {r.rerank_score:.4f} | {r.text}")
