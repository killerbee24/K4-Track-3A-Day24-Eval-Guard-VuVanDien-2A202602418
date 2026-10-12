# Blueprint CI/CD cho RAG và guardrails

Nhóm: K4-Track-3A-VuVanDien

Người phụ trách: Vũ Văn Điền - MSSV: 2A202602418

Đây là **đề xuất CI/CD**, không phải workflow đã được triển khai/chạy.
Nguồn kết quả: artifacts/ragas_50q.json, judge_results.json, guard_results.json.
Run timestamp: 2026-10-12T13:21:13.841053+00:00; guard models: ["claude-haiku-4-5-20251001"].
Models generation/evaluator/judge từ A/B: generation: ["claude-haiku-4-5-20251001"], evaluator: ["BAAI/bge-m3", "claude-haiku-4-5-20251001"], judge: ["claude-haiku-4-5-20251001"].

## Kiến trúc và failure action

Input → Presidio → NeMo input → RAG → NeMo output → response.
Request thực dừng sớm khi bị chặn; khác phép đo input layers chạy đủ hai tầng.

### Luồng dữ liệu và cơ chế xử lý lỗi (Data Flow & Failure Handling)

1. **Tầng 1 - Presidio PII Scanning & Redaction:**
   - Tin nhắn đầu vào của người dùng trước tiên đi qua Presidio Analyzer và Anonymizer cục bộ.
   - Nếu phát hiện PII nhạy cảm định danh (CCCD 12 số, CMND 9 số, số điện thoại Việt Nam, hoặc email cá nhân), request lập tức dừng sớm (`blocked_by: presidio`) và trả về thông báo từ chối lịch sự mà không tốn chi phí gọi LLM ở các tầng sau.
2. **Tầng 2 - NeMo Input Rails:**
   - Nếu đầu vào không chứa PII, request được gửi tới NeMo Guardrails chạy luồng `self_check_input`.
   - Kiểm tra các cuộc tấn công jailbreak, prompt injection, đóng vai giả mạo quyền hạn hoặc câu hỏi hoàn toàn lệch chủ đề công ty (off-topic). Nếu vi phạm, request dừng ngay lập tức với `blocked_by: nemo_input`.
3. **Tầng 3 - Pipeline RAG Core:**
   - Các yêu cầu hợp lệ được chuyển vào pipeline Hybrid Search (Dense Vector BGE-M3 + BM25 trên Qdrant) và lọc qua CrossEncoder Reranker.
   - LLM sinh câu trả lời có trích dẫn từ các đoạn văn bản chính sách được xếp hạng cao nhất.
   - Nếu hệ thống LLM gặp sự cố mạng hoặc timeout, kích hoạt cơ chế `extractive_fallback` trích xuất trực tiếp đoạn văn bản gốc có score cao nhất làm câu trả lời khẩn cấp.
4. **Tầng 4 - NeMo Output Rails:**
   - Câu trả lời do LLM sinh ra cùng câu hỏi gốc được đưa qua `self_check_output` và lớp lọc chính sách cấu trúc.
   - Kiểm tra xem output có bị rò rỉ dữ liệu lương cá nhân, mật khẩu hệ thống quản trị (kể cả mật khẩu test/demo), hay dữ liệu nhạy cảm hay không.
   - Nếu phát hiện vi phạm, câu trả lời bị chặn và thay thế hoàn toàn bằng câu từ chối chuẩn mực (`OUTPUT_REFUSAL`).
5. **Ghi log và bảo mật Secrets:**
   - Mọi log hệ thống chỉ lưu trữ văn bản đã được che/redact PII.
   - Toàn bộ API keys và thông tin xác thực quản lý nghiêm ngặt qua Vault/Environment Variables, tuyệt đối không in ra log hay trả về phía client.

## Phạm vi và số đo latency

Bắt buộc Task 12: **input_layers_sequential**, Presidio + NeMo input, không
short-circuit. Engines tạo trước đo; có hai warm-up thật không tính vào mẫu.
Percentile nội suy tuyến tính từ raw samples; tổng từ tổng từng sample.

Số mẫu timed: 20; warm-up: 2;
phương pháp: linear.

| Layer / scope | P50 ms | P95 ms | P99 ms | Tình trạng |
|---|---|---|---|---|
| Presidio | 14.67 ms | 16.31 ms | 17.25 ms | Đạt chuẩn hiệu năng cao |
| NeMo input | 1553.49 ms | 3114.42 ms | 3324.90 ms | Bottleneck do network roundtrip tới cloud LLM |
| Input guard sequential | 1567.04 ms | 3130.10 ms | 3338.51 ms | Vượt ngân sách 500ms |
| RAG | chưa đo | chưa đo | chưa đo | Ngoài phạm vi bắt buộc |
| NeMo output | chưa đo | chưa đo | chưa đo | Ngoài phạm vi bắt buộc |
| Full guard / short-circuit request | chưa đo | chưa đo | chưa đo | Không suy từ input_guard_ms |

Input-layer budget target: 500ms; kết quả thực tế/budget_ok: P95 = 3130.10 ms / budget_ok = False.

### Phân tích điểm nghẽn và giải pháp tối ưu

- **Điểm nghẽn (Bottleneck):** Presidio chạy local CPU với biểu thức chính quy tối ưu nên độ trễ cực thấp (P95 chỉ 16.31 ms, chiếm chưa tới 1% tổng thời gian). Tuy nhiên, NeMo input guard phụ thuộc hoàn toàn vào lời gọi mạng tới API Claude Haiku từ xa, dẫn đến độ trễ P95 lên tới 3114.42 ms, vượt ngân sách P95 500ms của lab.
- **Kế hoạch cải tiến trong môi trường Production:**
  - Thay thế lời gọi cloud LLM ở NeMo input guard bằng một Small Language Model (SLM) triển khai cục bộ (như Qwen-2.5-7B hoặc Llama-3.2-3B lượng tử hóa 4-bit chạy trên GPU nội bộ), hoặc sử dụng mô hình nhị phân phân loại intent (ví dụ DeBERTa-v3 finetuned) để hạ P95 xuống < 120 ms.
  - Áp dụng Semantic Caching cho các câu hỏi phổ biến để bỏ qua bước guardrail khi input hoàn toàn khớp với truy vấn sạch đã biết.
  - Các tầng chưa đo (RAG generation, NeMo output rail, full request): Trong giai đoạn sau sẽ thiết lập đo lường end-to-end với Prometheus middleware, thực hiện 50 mẫu warmup và ghi nhận timestamp chuẩn microsecond.

## CI gates đề xuất

- RAGAS faithfulness ≥0.75, avg_score ≥0.65 trên 50 câu.
- Attacks ≥18/20 cho CI đề xuất; clean 8/8 allowed; output cases đúng.
- Full guard P95 <500ms chỉ áp dụng sau khi thực sự đo full guard.

Mốc bắt buộc lab vẫn attacks ≥15/20; bonus ≥18/20 kèm clean controls đạt.

### Đề xuất tích hợp Pipeline CI/CD (GitHub Actions / GitLab CI)

Quy trình tự động hóa kiểm thử chất lượng trước khi triển khai:

1. **Job 1 - Offline Verification (Fast Gate - Chạy trong 1 phút):**
   - Lệnh thực thi: `python scripts/check_lab.py --with-tests`
   - Kiểm tra toàn bộ 91 offline unit tests, hợp đồng schema dữ liệu, định dạng báo cáo và logic toán học. Nếu có bất kỳ fail nào, job lập tức trả về exit code 1 và chặn merge pull request.
2. **Job 2 - Synthetic Guardrail Regression (Staging Gate):**
   - Kiểm tra bộ kiểm thử bảo mật 28 câu: bắt buộc đạt attacks ≥ 15/20, clean false_positive_rate = 0 (8/8 clean allowed), và 4/4 output safety cases chính xác.
3. **Job 3 - Performance & Quality Gate (Nightly / Release Gate):**
   - Chạy định kỳ trên staging server để kiểm tra ngưỡng RAGAS: `faithfulness >= 0.70`, `avg_score >= 0.65`.
   - Nếu bất kỳ tiêu chí chất lượng nào suy giảm (drift), hệ thống tự động gửi thông báo tới đội ngũ kỹ thuật và ngăn chặn auto-deploy lên production.

## Monitoring và cải tiến

Giám sát vận hành liên tục trên hệ thống Production:

1. **Chỉ số chất lượng và vận hành thực tế:**
   - RAGAS mean/worst distribution: Mean toàn bộ đạt 0.7138 (factual: 0.7613, adversarial: 0.7287, multi_hop: 0.6513); worst distribution: multi_hop (0.6513).
   - Cohen’s κ: 1.0 (Đồng thuận hoàn hảo giữa Judge và chuyên gia con người).
   - Attacks passed: 15/20 (75.0%); clean false_positive_rate: 0.0 (8/8 clean controls được cho phép hoàn toàn).
   - Latency Sequential Guard P95: 3130.10 ms (Presidio P95: 16.31 ms, NeMo Input P95: 3114.42 ms).
2. **Hệ thống cảnh báo và xử lý sự cố:**
   - Thiết lập alert khi false-positive rate vượt quá 1% trong 1 giờ (bị chặn nhầm câu hỏi hợp lệ).
   - Cảnh báo khi tỷ lệ jailbreak lọt qua guardrail > 0%.
   - Đội ngũ trực vận hành: AI Platform Engineer và Security Officer chịu trách nhiệm tiếp nhận và xử lý cảnh báo trong vòng 30 phút.
3. **Kế hoạch cải tiến 4 điểm cụ thể:**
   - Áp dụng Query Decomposition cho các câu hỏi `multi_hop` để kéo điểm trung bình từ 0.6513 lên > 0.75.
   - Bổ sung thêm các flow Colang và mẫu đối kháng phức tạp để nâng tỷ lệ chặn attacks từ 15/20 lên ≥ 18/20.
   - Chuyển NeMo Guardrails sang mô hình ONNX / TensorRT-LLM cục bộ để giảm độ trễ P95 từ 3130 ms xuống dưới ngưỡng 500 ms.
   - Thêm bộ lọc định dạng câu trả lời Markdown để tránh hiện tượng RAGAS không trích xuất được statement.
