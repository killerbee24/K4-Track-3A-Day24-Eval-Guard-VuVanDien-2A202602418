from __future__ import annotations

"""Module 5: enrichment through the configured LLM with offline fallbacks."""

import json
import os
import re
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.llm import generate_text, is_enrichment_configured, safe_error


@dataclass
class EnrichedChunk:
    original_text: str
    enriched_text: str
    summary: str
    hypothesis_questions: list[str]
    auto_metadata: dict
    method: str


def _summary_fallback(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.replace("\n", " ").strip())
    return " ".join(sentences[:2])


def _questions_fallback(text: str, count: int) -> list[str]:
    sentences = [s.strip() for s in re.split(r"[.!?\n]", text) if len(s.strip()) > 10]
    return [f"{s}?" for s in sentences[: max(0, count)]]


def _metadata_fallback() -> dict:
    return {"topic": "general", "entities": [], "category": "policy", "language": "vi"}


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    result = json.loads(text)
    if not isinstance(result, dict):
        raise TypeError("Enrichment JSON phải là object.")
    return result


def summarize_chunk(text: str) -> str:
    if text.strip() and is_enrichment_configured():
        try:
            return generate_text(
                "Tóm tắt trong 2-3 câu ngắn bằng tiếng Việt. Không thêm thông tin.",
                text,
                max_tokens=150,
            )
        except Exception as e:  # noqa: BLE001 - Required fallback at provider boundary.
            print(f"  ⚠️  Summary fallback: {safe_error(e)}")
    return _summary_fallback(text)


def generate_hypothesis_questions(text: str, n_questions: int = 3) -> list[str]:
    if n_questions <= 0 or not text.strip():
        return []
    if is_enrichment_configured():
        try:
            response = generate_text(
                f"Tạo {n_questions} câu hỏi mà đoạn văn có thể trả lời. Mỗi câu một dòng.",
                text,
                max_tokens=200,
            )
            questions = [
                re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", q).strip()
                for q in response.splitlines()
                if q.strip()
            ]
            return questions[:n_questions]
        except Exception as e:  # noqa: BLE001 - Required fallback at provider boundary.
            print(f"  ⚠️  HyQA fallback: {safe_error(e)}")
    return _questions_fallback(text, n_questions)


def contextual_prepend(text: str, document_title: str = "") -> str:
    context = (
        f"Trích từ {document_title}."
        if document_title
        else "Trích từ tài liệu chính sách nội bộ."
    )
    if text.strip() and is_enrichment_configured():
        try:
            context = generate_text(
                "Viết một câu ngắn mô tả chủ đề đoạn văn trong tài liệu. Không thêm sự kiện mới.",
                f"Tài liệu: {document_title}\n\nĐoạn văn:\n{text}",
                max_tokens=100,
            )
        except Exception as e:  # noqa: BLE001 - Required fallback at provider boundary.
            print(f"  ⚠️  Contextual fallback: {safe_error(e)}")
    return f"{context}\n\n{text}"


def extract_metadata(text: str) -> dict:
    if text.strip() and is_enrichment_configured():
        try:
            return _parse_json(
                generate_text(
                    'Chỉ trả JSON: {"topic": "...", "entities": ["..."], '
                    '"category": "policy|hr|it|finance", "language": "vi|en"}. '
                    "Chỉ trích xuất thông tin có trong đoạn văn.",
                    text,
                    max_tokens=250,
                )
            )
        except Exception as e:  # noqa: BLE001 - Required fallback at provider boundary.
            print(f"  ⚠️  Metadata fallback: {safe_error(e)}")
    return _metadata_fallback()


def _enrich_single_call(text: str, source: str, allow_llm: bool = True) -> dict:
    fallback = {
        "summary": _summary_fallback(text),
        "questions": _questions_fallback(text, 3),
        "context": f"Trích từ {source}."
        if source
        else "Trích từ tài liệu chính sách nội bộ.",
        "metadata": _metadata_fallback(),
    }
    if not text.strip() or not allow_llm or not is_enrichment_configured():
        return fallback
    try:
        result = _parse_json(
            generate_text(
                "Phân tích đoạn văn và chỉ trả JSON với cấu trúc: "
                '{"summary": "tóm tắt 2-3 câu", "questions": ["câu hỏi 1?", "câu hỏi 2?"], '
                '"context": "1 câu mô tả vị trí/chủ đề đoạn văn", '
                '"metadata": {"topic": "...", "entities": [], "category": "policy|hr|it|finance", '
                '"language": "vi|en"}}. Không thêm thông tin không có trong tài liệu.',
                f"Tài liệu: {source}\n\nĐoạn văn:\n{text}",
                max_tokens=600,
            )
        )
        for key in ("summary", "context"):
            if not isinstance(result.get(key), str) or not result[key].strip():
                result[key] = fallback[key]
        questions = result.get("questions")
        result["questions"] = (
            [q.strip() for q in questions if isinstance(q, str) and q.strip()][:3]
            if isinstance(questions, list)
            else fallback["questions"]
        )
        if not isinstance(result.get("metadata"), dict):
            result["metadata"] = fallback["metadata"]
        return result
    except Exception as e:  # noqa: BLE001 - Required fallback at provider boundary.
        print(f"  ⚠️  Combined enrichment fallback: {safe_error(e)}")
        return fallback


def enrich_chunks(
    chunks: list[dict], methods: list[str] | None = None, allow_llm: bool = True
) -> list[EnrichedChunk]:
    methods = ["combined"] if methods is None else methods
    enriched = []
    for i, chunk in enumerate(chunks):
        text = chunk["text"]
        original_metadata = chunk.get("metadata", {})
        source = original_metadata.get("source", "")
        if "combined" in methods:
            result = _enrich_single_call(text, source, allow_llm=allow_llm)
            summary = result["summary"]
            questions = result["questions"]
            enriched_text = f"{result['context']}\n\n{text}"
            auto_meta = result["metadata"]
        else:
            summary = summarize_chunk(text) if "summary" in methods else ""
            questions = generate_hypothesis_questions(text) if "hyqa" in methods else []
            enriched_text = (
                contextual_prepend(text, source) if "contextual" in methods else text
            )
            auto_meta = extract_metadata(text) if "metadata" in methods else {}
        # Preserve source and parent identifiers even if an LLM invents these keys.
        enriched.append(
            EnrichedChunk(
                original_text=text,
                enriched_text=enriched_text,
                summary=summary,
                hypothesis_questions=questions,
                auto_metadata={**auto_meta, **original_metadata},
                method="+".join(methods),
            )
        )
        if (i + 1) % 10 == 0 or i + 1 == len(chunks):
            print(f"  Enriched {i + 1}/{len(chunks)} chunks...", flush=True)
    return enriched


if __name__ == "__main__":
    sample = "Nhân viên chính thức được nghỉ phép năm 12 ngày làm việc mỗi năm."
    print(enrich_chunks([{"text": sample, "metadata": {"source": "policy.md"}}]))
