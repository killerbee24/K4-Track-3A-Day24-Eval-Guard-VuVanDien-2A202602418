# Phân tích lỗi Phase A

Nhóm: K4-Track-3A-VuVanDien

Người phụ trách: Vũ Văn Điền - MSSV: 2A202602418

Nguồn: `artifacts/ragas_50q.json`; run timestamp: 2026-10-12T16:04:58.665139+00:00.
Generation mode/fallback và điều kiện chạy: Chạy hoàn toàn bằng generation\_mode=llm (không fallback), pipeline RAG kết hợp HybridSearch (Dense BGE-M3 + BM25 Qdrant) và CrossEncoder Reranker.
Models generation/evaluator: generation: \["claude-haiku-4-5-20251001"] và evaluator: \["BAAI/bge-m3", "claude-haiku-4-5-20251001"].

## Điểm theo distribution

| Metric             | factual (20) | multi\_hop (20) | adversarial (10) |
| ------------------ | ------------ | --------------- | ---------------- |
| faithfulness       | 0.7520       | 0.5918          | 0.7320           |
| answer\_relevancy  | 0.6625       | 0.5137          | 0.6205           |
| context\_precision | 0.7925       | 0.7375          | 0.8150           |
| context\_recall    | 0.8383       | 0.7623          | 0.7472           |
| avg\_score         | 0.7613       | 0.6513          | 0.7287           |

## Bottom 10 và nguyên nhân

Bảng 10 câu hỏi có avg\_score thấp nhất trích xuất từ `artifacts/ragas_50q.json`:

| Rank | ID | Question                                                                                                                      | Distribution | Avg Score | Worst Metric      | Diagnosis                     | Suggested Fix                            |
| ---- | -- | ----------------------------------------------------------------------------------------------------------------------------- | ------------ | --------- | ----------------- | ----------------------------- | ---------------------------------------- |
| 1    | 22 | Nếu cần mua một chiếc laptop 30 triệu cho nhân viên mới, ai phê duyệt và cần gì từ phòng CNTT?                                | multi\_hop   | 0.2083    | answer\_relevancy | Answer doesn't match question | Improve prompt template                  |
| 2    | 39 | Mật khẩu tài khoản công ty cần đổi bao nhiêu ngày một lần và có bắt buộc đổi khác mật khẩu cũ không?                          | multi\_hop   | 0.2708    | answer\_relevancy | Answer doesn't match question | Improve prompt template                  |
| 3    | 5  | Muốn mua thiết bị trị giá 55 triệu cần ai phê duyệt?                                                                          | factual      | 0.3224    | answer\_relevancy | Answer doesn't match question | Improve prompt template                  |
| 4    | 48 | Nhân viên thử việc có được cấp thẻ bảo hiểm sức khỏe PVI không?                                                               | adversarial  | 0.4167    | answer\_relevancy | Answer doesn't match question | Improve prompt template                  |
| 5    | 30 | Đi công tác nước ngoài được tạm ứng tối đa bao nhiêu và ai phê duyệt?                                                         | multi\_hop   | 0.4375    | answer\_relevancy | Answer doesn't match question | Improve prompt template                  |
| 6    | 33 | Nhân viên Manager có thâm niên 12 năm: tổng phụ cấp hàng tháng và số ngày phép năm?                                           | multi\_hop   | 0.5398    | faithfulness      | LLM hallucinating             | Tighten system prompt, lower temperature |
| 7    | 21 | Một nhân viên Senior có 9 năm thâm niên được nghỉ bao nhiêu ngày phép năm và lương trong khoảng nào?                          | multi\_hop   | 0.5460    | answer\_relevancy | Answer doesn't match question | Improve prompt template                  |
| 8    | 31 | Nhân viên nghỉ việc sau khi được tài trợ khóa học 15 triệu: thời gian cam kết và số tiền phải hoàn trả nếu nghỉ sau 18 tháng? | multi\_hop   | 0.6000    | answer\_relevancy | Answer doesn't match question | Improve prompt template                  |
| 9    | 50 | Nhân viên Manager có thể dùng VPN cá nhân (NordVPN) khi WFH không?                                                            | adversarial  | 0.6398    | faithfulness      | LLM hallucinating             | Tighten system prompt, lower temperature |
| 10   | 46 | Nhân viên thử việc có được nghỉ phép năm không?                                                                               | adversarial  | 0.6800    | answer\_relevancy | Answer doesn't match question | Improve prompt template                  |

### Phân tích đối chiếu các ca đại diện

1. **Lỗi Relevancy trong Multi-hop (ID 22, ID 39, ID 21):**
   - Tại câu 22 (Rank 1, avg 0.2083): Câu hỏi yêu cầu 2 vế (ai phê duyệt laptop 30tr VÀ phòng CNTT cần gì). Context retrieval tìm thấy tài liệu mua sắm và xác nhận cấu hình CNTT, nhưng LLM trả lời dài dòng về quy trình chung, khiến vector embedding của câu trả lời bị phân tán và điểm `answer_relevancy` hạ xuống thấp.
   - Tại câu 21 (Rank 7, avg 0.5460): Yêu cầu tính cả phép năm và khung lương Senior. Retrieval tìm thấy tài liệu phép năm nhưng thiếu chunk khung lương, dẫn đến LLM tuyên bố "không tìm thấy thông tin lương trong context", làm giảm relevancy và completeness.
2. **Lỗi Version Conflict và Faithfulness trong Adversarial (ID 50, ID 48):**
   - Tại câu 50 (Rank 9, avg 0.6398): Bẫy hỏi về việc dùng VPN cá nhân khi WFH. Chính sách bảo mật cấm tuyệt đối, nhưng LLM bị ảo giác diễn giải "có thể dùng nếu đảm bảo an toàn", vi phạm tính trung thực (faithfulness).
   - Tại câu 48 (Rank 4, avg 0.4167): Bẫy phủ định về bảo hiểm PVI cho nhân viên thử việc. Context có chứa thông tin mâu thuẫn giữa bản nháp và bản chính thức, khiến câu trả lời không tập trung trực diện vào việc xác nhận có hay không.

## Matrix và nhóm yếu nhất

Matrix phân bố 4 metric x 3 distributions (đếm theo worst metric của từng câu hỏi trên toàn bộ 50 câu):

| Metric                     | factual (20) | multi\_hop (20) | adversarial (10) | Tổng theo Metric |
| -------------------------- | :----------: | :-------------: | :--------------: | :--------------: |
| faithfulness               |       1      |        5        |         1        |         7        |
| answer\_relevancy          |      17      |        14       |         7        |        38        |
| context\_precision         |       1      |        0        |         0        |         1        |
| context\_recall            |       1      |        1        |         2        |         4        |
| **Tổng theo Distribution** |    **20**    |      **20**     |      **10**      |      **50**      |

- Nhóm yếu theo mean thấp nhất: `multi_hop`; mean avg\_score: `0.6513` (thấp hơn `adversarial`: 0.7287 và `factual`: 0.7613).
- Worst metric xuất hiện nhiều nhất: `answer_relevancy`; số câu: `38` câu (chiếm 76% toàn bộ tập dữ liệu test).

### Giải thích nguyên nhân và đề xuất cải tiến

1. **Nguyên nhân** **`multi_hop`** **yếu nhất:**
   - Các câu hỏi `multi_hop` đòi hỏi kết hợp thông tin từ 2 đến 3 văn bản chính sách khác nhau (ví dụ: thâm niên + phép năm + lương, hoặc mua sắm + kiểm duyệt CNTT).
   - Pipeline hiện tại dùng single-turn retrieval với top-k cố định, khiến các chunk của vế thứ hai có nguy cơ bị đẩy ra khỏi top reranked context. Khi LLM thiếu một nửa context, câu trả lời bị cụt và giảm nghiêm trọng `faithfulness` (0.5918) cũng như `answer_relevancy` (0.5137).
2. **Nguyên nhân** **`answer_relevancy`** **là dominant worst metric:**
   - Prompt generation hiện tại khuyến khích mô hình trích dẫn nguồn ("Dựa trên context từ...") và liệt kê điều kiện dự phòng ("Lưu ý: Bảng thẩm quyền..."). Điều này làm tăng độ dài nhưng làm loãng trọng tâm câu trả lời so với câu hỏi gốc khi đánh giá bằng embedding cosine similarity trong RAGAS.
3. **Đề xuất khắc phục và kiểm chứng:**
   - Áp dụng kỹ thuật Query Decomposition (phân rã câu hỏi multi-hop thành 2 sub-queries) để retrieval thu thập đủ context cho cả 2 vế.
   - Siết chặt Generation Prompt: yêu cầu trả lời trực tiếp kết quả vào dòng đầu tiên, không lặp lại câu hỏi, không giải thích ngoài lề nếu không được yêu cầu.
   - Chạy lại `python scripts/run_experiments.py --phase a --live` để đối chiếu: kỳ vọng `multi_hop` avg\_score tăng từ 0.65 lên >0.75 và `answer_relevancy` tăng từ 0.51 lên >0.70.

## Bẫy adversarial và giới hạn

1. **Phân tích bẫy phiên bản (Version Conflict) và phủ định (Negation):**
   - Tập `adversarial` gồm 10 câu với điểm trung bình đạt 0.7287 (cao hơn multi-hop). Điều này cho thấy pipeline lọc phiên bản qua Hybrid Search và Reranker hoạt động khá hiệu quả với các câu phiên bản (như Q41 phép năm v2024 đạt điểm cao).
   - Tuy nhiên, các câu phủ định (Q46, Q48, Q50) vẫn chiếm vị trí trong Bottom 10 (Q46 rank 10, Q48 rank 4, Q50 rank 9) do mô hình generation đôi khi vẫn bị cuốn theo hướng khẳng định thay vì nhấn mạnh quy định cấm/không áp dụng.
2. **Giới hạn thực nghiệm:**
   - Tập dữ liệu gồm 50 câu (20/20/10) là bộ mẫu tiêu chuẩn của lab, chưa bao quát toàn diện mọi ngữ cảnh đối kháng tinh vi.
   - Mô hình generation là Claude Haiku qua MWAPI: tuy nhanh và tiết kiệm chi phí nhưng khả năng suy luận đa bước (multi-step reasoning) trên ngữ cảnh tiếng Việt phức tạp còn hạn chế so với Claude Sonnet hoặc GPT-4o.
   - Quá trình chạy thực tế phụ thuộc độ ổn định mạng và rate limit của API provider; một số câu có dạng liệt kê gạch đầu dòng cần được chuẩn hóa định dạng để RAGAS bóc tách statement ổn định nhất.
