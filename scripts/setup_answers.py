"""
Setup script: chạy Day 18 pipeline trên 50 câu hỏi → lưu artifacts/answers_50q.json

Chạy TRƯỚC khi bắt đầu Phase A:
    python scripts/setup_answers.py --live

Yêu cầu:
    1. Có 5 module m1-m5 với giao diện trong doc/PIPELINE_INTERFACE.md
       Script tự lắp module; không gọi src/pipeline.py.
    2. docker compose -f infra/docker-compose.yml up -d  (Qdrant đang chạy trên port 6333)
    3. .env có LLM_API_KEY và LLM_MODEL của MWAPI
"""
from __future__ import annotations

import json
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ROOT_DIR, TEST_SET_PATH, ANSWERS_PATH, GENERATION_MODEL


def check_day18_files() -> bool:
    required = [
        "src/m1_chunking.py", "src/m2_search.py", "src/m3_rerank.py",
        "src/m4_eval.py",     "src/m5_enrichment.py",
    ]
    missing = [f for f in required if not os.path.exists(os.path.join(ROOT_DIR, f))]
    if missing:
        print("\n❌ Thiếu files từ Day 18. Copy chúng vào src/ trước:\n")
        for f in missing:
            print(f"   cp <Day18>/src/{os.path.basename(f)} src/")
        return False
    print(f"✓ Day 18 source files: {len(required)}/{len(required)} found")
    return True


def build_pipeline():
    # This assembler calls m1/m2/m3/m5 directly, NOT src.pipeline.py.
    from src.m1_chunking import load_documents, chunk_hierarchical
    from src.m2_search import HybridSearch
    from src.m3_rerank import CrossEncoderReranker
    from src.m5_enrichment import enrich_chunks
    from config import RERANK_TOP_K

    print("\n[1/3] Chunking + enriching documents...")
    t0 = time.time()
    docs = load_documents()
    all_chunks = []
    for doc in docs:
        parents, children = chunk_hierarchical(doc["text"], metadata=doc["metadata"])
        for child in children:
            all_chunks.append({
                "text": child.text,
                "metadata": {**child.metadata, "parent_id": child.parent_id},
            })

    enriched = enrich_chunks(all_chunks)
    if enriched:
        if len(enriched) != len(all_chunks):
            raise ValueError("enrich_chunks must preserve chunk count/order; see doc/PIPELINE_INTERFACE.md")
        all_chunks = [{"text": e.enriched_text,
                       "metadata": {**original["metadata"], **e.auto_metadata}}
                      for original, e in zip(all_chunks, enriched)]
        print(f"  ✓ Enriched {len(enriched)} chunks ({time.time()-t0:.1f}s)")
    else:
        print(f"  ✓ Using {len(all_chunks)} raw chunks (M5 not implemented or no API key)")

    print("\n[2/3] Indexing (BM25 + Dense)...")
    t0 = time.time()
    search = HybridSearch()
    search.index(all_chunks)
    print(f"  ✓ Indexed {len(all_chunks)} chunks ({time.time()-t0:.1f}s)")

    print("\n[3/3] Loading reranker...")
    t0 = time.time()
    reranker = CrossEncoderReranker()
    print(f"  ✓ Reranker ready ({time.time()-t0:.1f}s)")

    return search, reranker, RERANK_TOP_K


def run_query(q: str, search, reranker, top_k: int, client=None) -> tuple[str, list[str], str, str | None]:
    from src.llm import generate_with_metadata, is_configured

    results = search.search(q)
    docs    = [{"text": r.text, "score": r.score, "metadata": r.metadata} for r in results]
    reranked = reranker.rerank(q, docs, top_k=top_k)
    contexts = [r.text for r in reranked] if reranked else [r.text for r in results[:3]]

    if (is_configured() or client is not None) and contexts:
        try:
            ctx = "\n\n".join(contexts)
            answer, used_model = generate_with_metadata(
                "Trả lời CHỈ dựa trên context. Nếu không có → nói 'Không tìm thấy.'",
                f"Context:\n{ctx}\n\nCâu hỏi: {q}",
                model=GENERATION_MODEL,
                max_tokens=384,
                client=client,
            )
            return answer, contexts, "llm", used_model
        except Exception as e:
            print(f"  ⚠️  LLM generation failed: {e}")

    return (contexts[0] if contexts else "Không tìm thấy thông tin."), contexts, "extractive_fallback", None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Assemble previous modules and generate 50 answers (API cost).")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("Generation/enrichment may call APIs. Pass --live after completing pre-class setup.")
    print("=" * 60)
    print("K4 / TRACK 3A SETUP — Generating answers for 50 questions")
    print("=" * 60)

    if not check_day18_files():
        sys.exit(1)

    with open(TEST_SET_PATH, encoding="utf-8") as f:
        test_set = json.load(f)
    print(f"✓ Loaded {len(test_set)} questions (factual/multi_hop/adversarial)")

    try:
        search, reranker, top_k = build_pipeline()
    except ImportError as e:
        print(f"\n❌ Import error: {e}")
        print("→ Đảm bảo bạn đã copy src/ từ Day 18 và đã pip install -r requirements/requirements.txt")
        sys.exit(1)

    print(f"\nRunning {len(test_set)} queries...")
    answers = []
    from src.llm import get_client, is_configured
    client = None
    if is_configured():
        client = get_client()
    t_start = time.time()

    for i, item in enumerate(test_set):
        answer, contexts, generation_mode, generation_model = run_query(item["question"], search, reranker, top_k, client)
        answers.append({
            "id":           item["id"],
            "distribution": item["distribution"],
            "question":     item["question"],
            "answer":       answer,
            "contexts":     contexts,
            "ground_truth": item["ground_truth"],
            "generation_mode": generation_mode,
            "generation_model": generation_model,
        })
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(test_set)}] done ({time.time()-t_start:.0f}s elapsed)")

    os.makedirs(os.path.dirname(ANSWERS_PATH), exist_ok=True)
    with open(ANSWERS_PATH, "w", encoding="utf-8") as f:
        json.dump(answers, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Saved {len(answers)} answers → artifacts/answers_50q.json")
    print(f"  Total time: {time.time()-t_start:.1f}s")
    print("\n→ Bây giờ bắt đầu Phase A:")
    print("     python scripts/run_experiments.py --phase a --live")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
