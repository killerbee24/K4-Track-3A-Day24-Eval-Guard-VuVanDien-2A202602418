from __future__ import annotations

"""
Module 1: Advanced Chunking Strategies
=======================================
Implement semantic, hierarchical, và structure-aware chunking.
So sánh với basic chunking (baseline) để thấy improvement.

Test: pytest tests/test_m1.py
"""

import glob
import hashlib
import os
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    DATA_DIR,
    HIERARCHICAL_CHILD_SIZE,
    HIERARCHICAL_PARENT_SIZE,
    SEMANTIC_THRESHOLD,
)


@dataclass
class Chunk:
    text: str
    metadata: dict = field(default_factory=dict)
    parent_id: str | None = None


def _extract_pdf_text(path: str) -> str:
    """Extract text layer từ PDF. Trả về "" nếu PDF là scan ảnh (không có text)."""
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages).strip()


def load_documents(data_dir: str = DATA_DIR) -> list[dict]:
    """Load tất cả markdown và PDF (có text layer) từ data/. (Đã implement sẵn)

    - .md: đọc trực tiếp.
    - .pdf: trích text layer bằng pypdf. PDF scan ảnh (không có text) bị bỏ qua
      kèm cảnh báo — RAG text-based không xử lý được scan nếu chưa OCR.
    """
    docs = []
    for fp in sorted(glob.glob(os.path.join(data_dir, "*.md"))):
        with open(fp, encoding="utf-8") as f:
            docs.append(
                {"text": f.read(), "metadata": {"source": os.path.basename(fp)}}
            )

    for fp in sorted(glob.glob(os.path.join(data_dir, "*.pdf"))):
        text = _extract_pdf_text(fp)
        if text:
            docs.append({"text": text, "metadata": {"source": os.path.basename(fp)}})
        else:
            print(
                f"  ⚠️  Bỏ qua {os.path.basename(fp)}: PDF scan ảnh, không có text layer (cần OCR)."
            )

    versions = {}
    for doc in docs:
        meta = doc["metadata"]
        title = re.search(r"^#\s+(.+)$", doc["text"], re.MULTILINE)
        meta["title"] = title.group(1) if title else meta["source"]
        version = re.search(r"Phiên bản:\s*([\d.]+)", doc["text"])
        effective = re.search(r"Ngày hiệu lực:\s*(\d{2}/\d{2}/\d{4})", doc["text"])
        if version:
            meta["version"] = version.group(1)
        if effective:
            meta["effective_date"] = effective.group(1)
        family = re.match(r"(.+)_v(\d+)\.md$", meta["source"])
        if family:
            meta["version_family"] = family.group(1)
            meta["version_order"] = int(family.group(2))
            versions[family.group(1)] = max(
                versions.get(family.group(1), 0), int(family.group(2))
            )
    for doc in docs:
        meta = doc["metadata"]
        meta["status"] = (
            "superseded"
            if meta.get("version_family") in versions
            and meta["version_order"] < versions[meta["version_family"]]
            else "current"
        )

    return docs


# ─── Baseline: Basic Chunking (để so sánh) ──────────────


def chunk_basic(
    text: str, chunk_size: int = 500, metadata: dict | None = None
) -> list[Chunk]:
    """
    Basic chunking: split theo paragraph (\\n\\n).
    Đây là baseline — KHÔNG phải mục tiêu của module này.
    (Đã implement sẵn)
    """
    metadata = metadata or {}
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current = ""
    for i, para in enumerate(paragraphs):
        if len(current) + len(para) > chunk_size and current:
            chunks.append(
                Chunk(
                    text=current.strip(),
                    metadata={**metadata, "chunk_index": len(chunks)},
                )
            )
            current = ""
        current += para + "\n\n"
    if current.strip():
        chunks.append(
            Chunk(
                text=current.strip(), metadata={**metadata, "chunk_index": len(chunks)}
            )
        )
    return chunks


# ─── Strategy 1: Semantic Chunking ───────────────────────


def chunk_semantic(
    text: str, threshold: float = SEMANTIC_THRESHOLD, metadata: dict | None = None
) -> list[Chunk]:
    """
    Split text by sentence similarity — nhóm câu cùng chủ đề.
    Tốt hơn basic vì không cắt giữa ý.
    """
    if not -1 <= threshold <= 1:
        raise ValueError("threshold must be between -1 and 1")
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n\n", text) if s.strip()]
    if not sentences:
        return []
    import numpy as np

    embeddings = _semantic_model().encode(sentences, normalize_embeddings=True)
    groups = [[sentences[0]]]
    for i in range(1, len(sentences)):
        a, b = embeddings[i - 1], embeddings[i]
        similarity = float(
            np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)
        )
        if similarity < threshold:
            groups.append([])
        groups[-1].append(sentences[i])
    return [
        Chunk(
            "\n".join(group),
            {**(metadata or {}), "strategy": "semantic", "chunk_index": i},
        )
        for i, group in enumerate(groups)
    ]


@lru_cache(maxsize=1)
def _semantic_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("all-MiniLM-L6-v2")


def _split_bounded(text: str, size: int) -> list[str]:
    """Prefer paragraph/word boundaries, but also bound a single long token."""
    if size <= 0:
        raise ValueError("chunk size must be positive")
    blocks = []
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        remaining = paragraph.strip()
        while len(remaining) > size:
            cut = remaining.rfind(" ", 0, size + 1)
            if cut <= size // 2:
                cut = size
            blocks.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        if remaining:
            blocks.append(remaining)
    result, current = [], ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > size:
            result.append(current)
            current = block
        else:
            current = candidate
    if current:
        result.append(current)
    return result


# ─── Strategy 2: Hierarchical Chunking ──────────────────


def chunk_hierarchical(
    text: str,
    parent_size: int = HIERARCHICAL_PARENT_SIZE,
    child_size: int = HIERARCHICAL_CHILD_SIZE,
    metadata: dict | None = None,
) -> tuple[list[Chunk], list[Chunk]]:
    """
    Parent-child hierarchy: retrieve child (precision) → return parent (context).
    Đây là default recommendation cho production RAG.

    Returns:
        (parents, children) — mỗi child có parent_id link đến parent.
    """
    if not 0 < child_size < parent_size:
        raise ValueError("Require 0 < child_size < parent_size")
    meta = metadata or {}
    identity = hashlib.sha1(
        (meta.get("source", "") + "\n" + text).encode("utf-8")
    ).hexdigest()[:16]
    parents, children = [], []
    for i, parent_text in enumerate(_split_bounded(text, parent_size)):
        pid = f"{identity}_parent_{i}"
        parents.append(
            Chunk(
                parent_text,
                {
                    **meta,
                    "parent_id": pid,
                    "chunk_type": "parent",
                    "strategy": "hierarchical",
                },
            )
        )
        for child_text in _split_bounded(parent_text, child_size):
            children.append(
                Chunk(
                    child_text,
                    {
                        **meta,
                        "chunk_type": "child",
                        "strategy": "hierarchical",
                        "chunk_index": len(children),
                    },
                    pid,
                )
            )
    return parents, children


# ─── Strategy 3: Structure-Aware Chunking ────────────────


def chunk_structure_aware(text: str, metadata: dict | None = None) -> list[Chunk]:
    """
    Parse markdown headers → chunk theo logical structure.
    Giữ nguyên tables, code blocks, lists — không cắt giữa chừng.
    """
    chunks, lines, section, fence = [], [], "", ""

    def flush():
        content = "\n".join(lines).strip()
        if content:
            chunks.append(
                Chunk(
                    content,
                    {
                        **(metadata or {}),
                        "section": section,
                        "strategy": "structure",
                        "chunk_index": len(chunks),
                    },
                )
            )

    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)[0]
            fence = "" if fence == token else (token if not fence else fence)
        header = re.match(r"^#{1,3}\s+.+$", line) if not fence else None
        if header:
            flush()
            lines = []
            section = line.strip()
        lines.append(line)
    flush()
    return chunks


# ─── A/B Test: Compare All Strategies ────────────────────


def compare_strategies(documents: list[dict]) -> dict:
    """
    Run all strategies on documents and compare.
    (Đã implement sẵn — sẽ hoạt động khi bạn implement 3 strategies ở trên)
    """

    def _stats(chunk_list):
        lengths = [len(c.text) for c in chunk_list]
        if not lengths:
            return {"count": 0, "avg_len": 0, "min_len": 0, "max_len": 0}
        return {
            "count": len(lengths),
            "avg_len": round(sum(lengths) / len(lengths)),
            "min_len": min(lengths),
            "max_len": max(lengths),
        }

    basic, semantic, parents, children, structure = [], [], [], [], []
    for document in documents:
        text, meta = document["text"], document.get("metadata", {})
        basic.extend(chunk_basic(text, metadata=meta))
        semantic.extend(chunk_semantic(text, metadata=meta))
        doc_parents, doc_children = chunk_hierarchical(text, metadata=meta)
        parents.extend(doc_parents)
        children.extend(doc_children)
        structure.extend(chunk_structure_aware(text, metadata=meta))

    results = {
        "basic": _stats(basic),
        "semantic": _stats(semantic),
        "hierarchical": {**_stats(children), "parents": len(parents)},
        "structure": _stats(structure),
    }

    print(f"{'Strategy':<15} {'Chunks':>7} {'Avg':>5} {'Min':>5} {'Max':>5}")
    for name, s in results.items():
        print(
            f"{name:<15} {s['count']:>7} {s['avg_len']:>5} {s['min_len']:>5} {s['max_len']:>5}"
        )

    return results


if __name__ == "__main__":
    docs = load_documents()
    print(f"Loaded {len(docs)} documents")
    results = compare_strategies(docs)
    for name, stats in results.items():
        print(f"  {name}: {stats}")
