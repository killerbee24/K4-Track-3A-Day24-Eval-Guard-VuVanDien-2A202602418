# Hợp đồng tích hợp pipeline RAG

## Setup thực sự gọi phần nào

`scripts/setup_answers.py` **tự lắp pipeline** từ m1/m2/m3/m5, rồi tự gọi generation.
Nó không import hoặc gọi `src/pipeline.py`. File pipeline cũ có thể giữ tham
khảo, nhưng không bắt buộc nếu năm module và giao diện bên dưới đầy đủ.
Phase A dùng thêm `m4_eval.evaluate_ragas()`.

Các module bài trước không đi kèm starter. Chép mã trước lớp, hoặc viết adapter
với đúng tên/giao diện; đừng chỉ đổi tên file rồi giả định các kiểu trả về khớp.

## Bảng giao diện bắt buộc

| Nơi gọi | Chữ ký | Trả về / thuộc tính cần có |
|---|---|---|
| m1 | `load_documents()` | list dict: `text: str`, `metadata: dict`; đọc corpus từ config.DATA_DIR |
| m1 | `chunk_hierarchical(text, metadata=...)` | tuple `(parents, children)`; mỗi child có `.text: str`, `.metadata: dict`, `.parent_id` |
| m5 | `enrich_chunks(chunks)` | list đúng số lượng/thứ tự đầu vào; mỗi item có `.enriched_text: str`, `.auto_metadata: dict`; `[]` là fallback dùng chunks gốc |
| m2 | `HybridSearch()` | instance hỗ trợ `index(chunks)` và `search(question)` |
| m2 | `index(chunks)` | chunks là list dict `text, metadata`; lưu index, không cần giá trị return |
| m2 | `search(question)` | list object có `.text: str`, `.score: float`, `.metadata: dict` |
| m3 | `CrossEncoderReranker()` | instance hỗ trợ `rerank(question, docs, top_k=...)` |
| m3 | `rerank(question, docs, top_k)` | docs là list dict `text, score, metadata`; trả list object có `.text`; `[]` dùng top 3 search results |
| m4 | `evaluate_ragas(questions, answers, contexts, ground_truths)` | bốn list cùng độ dài; contexts là list[list[str]]; trả dict có `per_question` đúng số câu |
| m4 | từng item `per_question` | object có 4 thuộc tính: faithfulness, answer_relevancy, context_precision, context_recall; float Python hữu hạn trong [0,1] |
| m4 | `metadata.evaluator_models` trong dict trả về | list không rỗng các model IDs thực sự dùng trong lượt evaluation, gồm LLM/embedding nếu được dùng; không lấy JUDGE_MODEL thay thế |

M1 metadata được giữ qua chunking; setup giữ parent_id và merge metadata khi
enrich. Nếu m5 thay số lượng hoặc thứ tự chunks, phải sửa adapter có ánh xạ rõ,
không zip âm thầm làm mất câu/chunk. Nếu m4 trả dict thay object, adapter chuyển
record sang object hoặc code Task 2 phải đọc mapping có chủ ý.
Nếu metric là scalar NumPy/Pandas, chuyển bằng `float(value)` trước khi tạo
RagasResult và xuất JSON; không giữ NaN hoặc tự thay NaN bằng điểm giả.
M4 phải ghi model IDs từ các evaluator được cấu hình/thực sự gọi trong lượt chạy.
Task 2 trả `RagasEvaluation(results, evaluator_models)`, trong đó `results` giữ
50 `RagasResult`, còn `evaluator_models` lấy từ metadata m4 vừa trả về. Runner
dùng thông tin này cho Phase A; nếu thiếu thì báo lỗi, không đoán từ model judge.

Ví dụ chuyển một record metric dạng dict sang giao diện thuộc tính:

```python
from types import SimpleNamespace
record = {"faithfulness": 0.8, "answer_relevancy": 0.7,
          "context_precision": 0.6, "context_recall": 0.5}
metric_object = SimpleNamespace(**record)
```

Đây là ví dụ hình dạng dữ liệu, không phải số đo của pipeline. Không dùng các
giá trị ví dụ này làm report.

## Giao diện setup và nguồn answers

`build_pipeline()` trả `(search, reranker, top_k)`.
`run_query(q, search, reranker, top_k, client=None)` trả
`(answer, contexts, generation_mode, generation_model)`. Client provider được reuse qua 50 câu,
không khởi tạo lại cho mỗi query. `generation_mode` là `llm` hoặc
`extractive_fallback`; fallback khi không có key/contexts hoặc generation lỗi
phải được mô tả trong phân tích.
`generation_model` ghi model identifier provider trả về nếu có, hoặc model ID
đã truyền vào lời gọi generation; dùng `null` khi extractive fallback. Generation
dùng `config.GENERATION_MODEL`, tách khỏi `config.JUDGE_MODEL`.

`artifacts/answers_50q.json` có đúng 50 id từ test set, question/distribution/ground_truth
khớp nguồn. Không thay answer bằng ground_truth. Trước Phase A, xác nhận contexts
đến từ search/rerank thực tế và bốn metric từ m4 có thể đối chiếu theo thứ tự.

Unit tests dùng fake module để kiểm tra việc truyền dữ liệu, không chứng minh
module RAG bài trước đã chạy trên Qdrant/model thật. Chạy setup thực tế trước
lớp sau khi hoàn tất [ENVIRONMENT.md](ENVIRONMENT.md).
