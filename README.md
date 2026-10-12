# K4 Track 3A — Production Eval + Guardrail Stack

**Bài nhóm: mỗi nhóm dùng và nộp một repo chung của trưởng nhóm.**

**Thời lượng trên lớp:** 15 phút kiểm tra sẵn sàng + 90 phút thực hành
(Phase A/B/C, mỗi phase 30 phút).

**Điểm:** 100 điểm bắt buộc + tối đa 10 bonus cho bài lab.

**Repo đề bài:** [K4-Track-3A-Day24-Eval-Guard](https://github.com/VinUni-AI20k/K4-Track-3A-Day24-Eval-Guard).
Repo bài nộp nhóm: `K4-L3-DAY24-TenNhom-Eval-Guard`.

## Bài lab này nói về cái gì?

Ở bài trước, nhóm đã xây **RAG**: hệ thống tìm các đoạn tài liệu liên quan rồi
dùng chúng để trả lời câu hỏi. Bài này dùng lại pipeline đó với bộ tài liệu
chính sách nhân sự và CNTT của công ty để trả lời ba câu hỏi:

- **RAG trả lời đúng và có căn cứ không?** Đánh giá 50 câu hỏi bằng RAGAS,
  tìm câu trả lời yếu và phân tích lỗi lấy tài liệu hoặc sinh câu trả lời.
- **Có thể tin LLM chấm câu trả lời đến mức nào?** Cho LLM so sánh câu trả lời,
  đổi thứ tự để kiểm tra thiên lệch và đối chiếu với nhãn người đánh giá.
- **Hệ thống có chặn yêu cầu và câu trả lời không an toàn không?** Phát hiện
  dữ liệu cá nhân, thử các câu tấn công và câu hợp lệ, kiểm tra output và đo độ trễ.

**Học viên cần hoàn thiện các hàm TODO và chạy thực nghiệm thật.** Repo đã cung
cấp dữ liệu kiểm thử, runner, phần lưu JSON và checker; nhóm phải mang các module
RAG từ bài trước vào. Kết quả cuối là một bộ đánh giá và bảo vệ có bằng chứng,
kèm phân tích và đề xuất CI/CD; chưa mặc nhiên chứng minh hệ thống sẵn sàng production.

**Trạng thái khi tải về:** các hàm bài tập còn TODO, TEAM và báo cáo Markdown là
mẫu chưa điền; `artifacts/` chỉ có `.gitkeep`. Dữ liệu trong `fixtures/` là bộ
kiểm thử được cấp sẵn, không phải kết quả thực nghiệm của nhóm.

## Tổng quan: nhóm cần làm gì, theo thứ tự nào?

| Bước | Việc cần làm |
|---|---|
| 1. Chuẩn bị trước lớp | Tạo repo chung, cài môi trường, chép m1–m5, tải model, chạy Qdrant và sinh 50 answers |
| 2. Phase A — Tasks 1–4 | Nhóm câu hỏi, chạy 4 metric RAGAS, lấy bottom 10 và phân tích nhóm lỗi |
| 3. Phase B — Tasks 5–8 | Judge 5 cặp A/B theo hai thứ tự; đối chiếu 10 nhãn tốt/xấu với người; tính κ và bias |
| 4. Phase C — Tasks 9a–12 | Phát hiện/ẩn PII, kiểm tra input/output, chạy attacks và clean controls, đo latency |
| 5. Tổng hợp — Task 13 | Điền blueprint, đóng góp từng người; kiểm tra, commit/push và nộp link |

Phase A có **20 factual, 20 multi-hop, 10 adversarial**: câu tra cứu trực tiếp,
câu cần kết hợp/suy luận và câu có bẫy phiên bản/phủ định.

Phase B phân biệt
**chọn A/B/tie** với **gán nhãn tốt/xấu 0/1**; hai loại kết quả không thay thế nhau.
Nhãn 0/1 phải đánh giá đúng `model_answer` trong bộ nhãn người, không dùng answer
pipeline mới và không gửi `human_label`/`human_note` vào judge.

Phase C cần ít nhất **15/20 attacks**, **8/8 câu sạch được allowed**, kiểm tra
**4 output cases** và đo ít nhất **20 mẫu latency** sau warm-up. Đạt **18/20
attacks**, kèm clean controls đạt, là điều kiện bonus Phase C.

## Cuối bài phải nộp những gì?

**Tất cả thành viên nhóm nộp một link repo GitHub chung. Ai cũng phải có commit, dùng để chấm sau này.** . Repo phải chứa đủ các phần sau, không chỉ source code:

- **Mã nguồn:** năm module RAG m1–m5 của nhóm và ba module `src/phase_*.py`
  đã hoàn thiện; giữ scripts, tests, fixtures, corpus và cấu hình của starter.
- **Bốn file JSON trong `artifacts/`:** `answers_50q.json`, `ragas_50q.json`,
  `judge_results.json`, `guard_results.json`. Đây là dữ liệu và bằng chứng chạy
  thật, được setup/runner tạo ra; cần commit sau khi kiểm tra secrets.
- **Ba báo cáo Markdown trong `doc/reports/`:** `failure_clusters.md`
  giải thích lỗi RAG; `bias_report.md` giải thích độ tin cậy/thiên lệch judge;
  `blueprint.md` đề xuất kiến trúc, CI gates, monitoring và cải tiến, không mặc
  nhiên là workflow đã chạy. Nhóm điền các báo cáo từ kết quả JSON.
- **`doc/TEAM.md`:** danh sách thành viên, MSSV, phân công, bằng chứng đóng góp
  và một mục `INDIVIDUAL` cho mỗi người, nêu việc đã làm và điều đã học.

Không dùng TEAM thay báo cáo kỹ thuật. Không nộp API key, `.env`, virtualenv hoặc
cache model. Checklist đầy đủ nằm trong [SUBMISSION.md](doc/SUBMISSION.md).

## Cấu trúc repo

- `src/`: hàm bài tập TODO và phần hỗ trợ.
- `scripts/`: setup, runner và checker; chạy từ gốc repo.
- `fixtures/`: bộ câu hỏi và dữ liệu kiểm thử được cấp sẵn.
- `data/`: tài liệu nguồn cho RAG.
- `doc/`: đề bài, hướng dẫn, TEAM và mẫu báo cáo.
- `requirements/`: dependencies và constraints.
- `infra/`: Docker Compose; `guardrails/`: cấu hình guard.
- `tests/`: tests offline và integration tùy chọn.
- `artifacts/`: kết quả nhóm tự tạo sau khi làm bài.

## Tài liệu hướng dẫn

Đọc [đề bài](doc/ASSIGNMENT.md), [checkpoints](doc/CHECKPOINTS.md),
[rubric](doc/RUBRIC.md), [quy định](doc/RULES.md) và [nộp bài](doc/SUBMISSION.md).
Giao diện mã bài trước nằm trong [PIPELINE_INTERFACE.md](doc/PIPELINE_INTERFACE.md);
schema và cách chạy nằm trong [REPORT_SCHEMAS.md](doc/REPORT_SCHEMAS.md). Nếu dùng
Claude qua MWAPI, làm theo [MWAPI_SETUP.md](doc/MWAPI_SETUP.md) trước khi chạy API thật.

## Chuẩn bị trước buổi học

Môi trường mục tiêu là **Python 3.11**. Dùng `requirements/requirements-test.lock.txt` cho
unit tests offline và `requirements/requirements.txt` cùng `requirements/constraints-core.txt` cho full
runtime. Cài dependencies/build tools, tải model, indexing và sinh answers
**trước buổi học**; các việc này không thuộc 15 phút kiểm tra sẵn sàng.

1. Làm theo [ENVIRONMENT.md](doc/ENVIRONMENT.md), chuẩn bị compiler, Docker và
   dependencies trước buổi học. Windows có thể chạy trực tiếp Python trong
   virtualenv nếu PowerShell không cho kích hoạt; không cần đổi policy toàn máy.
2. Đưa năm module `m1`–`m5` từ bài RAG trước vào `src/`, đối chiếu bảng giao
   diện. `pipeline.py` có thể giữ làm tham khảo; setup **không gọi file này**.
3. Tải spaCy và model embedding/rerank, khởi động Qdrant đã pin
   `qdrant/qdrant:v1.9.7`; kiểm tra key trong `.env`.
4. Từ gốc repo, sinh answers trước buổi học:

```bash
python scripts/setup_answers.py --live
```

Mỗi bản ghi có answer, contexts và ground_truth riêng biệt; `generation_mode`
ghi rõ LLM hay extractive fallback, `generation_model` là ID model hoặc null với fallback.
Không dùng ground truth thay answer để tạo điểm đẹp. Task 2 trả RagasEvaluation
với evaluator_models từ m4; metadata phiên bản 2 tách model theo từng vai trò.

## Kiểm tra trên lớp và chạy thực nghiệm

Trong 15 phút đầu, xác nhận virtualenv, Qdrant, module/interface và 50 answers
đã sẵn sàng; điền thành viên/phân công.

1. Hoàn thành các hàm TODO theo ba phase. Tests mặc định dùng mock, không gọi
   API, không tải spaCy/model. Khi chưa implement, student tests phải fail.
2. Chạy unit tests; dùng `-m support` khi chỉ kiểm tra phần scaffold cung cấp:

```bash
python -m pytest tests/ -q
python -m pytest tests/ -m support -q
```

3. Sau khi implement, chạy một batch thực nghiệm thật. `--live` xác nhận dùng
   API và mạng; có chi phí. Runner không tạo báo cáo hợp lệ từ TODO còn nguyên.

```bash
python scripts/run_experiments.py --phase a --live
python scripts/run_experiments.py --phase b --live
python scripts/run_experiments.py --phase c --live --latency-samples 20
```

4. Điền ba báo cáo Markdown và TEAM, rồi kiểm tra bằng chứng đã lưu:

```bash
python scripts/check_lab.py
```

Checker mặc định không chạy pytest lại và không gọi API. Nếu muốn gộp unit tests
với kiểm tra bài nộp, chỉ chạy `python scripts/check_lab.py --with-tests`.
Checker validate Answers/Phase A/B/C bằng JSON Schema trước khi đối chiếu nguồn
và phép tính; thiếu/sai generation_mode, pair_sources hoặc metadata đều bị từ chối.
Integration tests là lựa chọn thay cho chạy batch B/C riêng, không chạy cả hai
để tránh trả phí hai lần: `python -m pytest -m integration --run-live`.

Nộp link qua vlearn. Deadline mặc định là
**23:59 ngày diễn ra lab**
