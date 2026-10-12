# Nhóm thực hiện K4 Track 3A

Tên nhóm: K4-Track-3A-VuVanDien

Repo chung: https://github.com/killerbee24/K4-Track-3A-Day24-Eval-Guard-VuVanDien-2A202602418

Trưởng nhóm/người nộp: Vũ Văn Điền - MSSV: 2A202602418

Ngày lab/deadline áp dụng: 2026-10-12 23:59:59 — Asia/Ho\_Chi\_Minh (UTC+07:00)

Commit dùng để chấm: eed9d092cf11f3ba63ae7b168b3b1c6899245b11

Mỗi nhóm nộp một repo. Điền đủ thành viên và một mục INDIVIDUAL cho từng người.
Thêm/xóa rows để khớp nhóm thật; mẫu ba rows không ép nhóm phải có ba người.

## Thành viên và phân công

| STT | Họ và tên   | MSSV        | Vai trò / công việc thật                                | Bằng chứng                                                                   |
| --- | ----------- | ----------- | ------------------------------------------------------- | ---------------------------------------------------------------------------- |
| 1   | Vũ Văn Điền | 2A202602418 | Toàn bộ Phase A, B, C, RAG integration, CI/CD Blueprint | answers\_50q.json, judge\_results.json, guard\_results.json, ragas\_50q.json |

Người tích hợp/chạy batch/nộp link: Vũ Văn Điền - Tự thực hiện toàn bộ tích hợp m1-m5, adapter LLM, chạy thực nghiệm live, thẩm định hợp đồng báo cáo và nộp bài cá nhân.

## Môi trường và chuẩn bị trước lớp

OS/Python/compiler: Windows 11 Home x64, Python 3.11.9, MSVC v143 (Microsoft C++ Build Tools).
Virtualenv/dependencies/imports: Môi trường .venv-tests và .venv, cài đặt từ lock file, pip check đạt không lỗi dependency, imports ragas, nemoguardrails, presidio\_analyzer, spacy thành công.
Models/Qdrant/50 answers đã chuẩn bị: Model Claude Haiku (claude-haiku-4-5-20251001) qua MWAPI, embedding BAAI/bge-m3; 50 câu hỏi đã được sinh hoàn chỉnh và lưu tại artifacts/answers\_50q.json với contexts đầy đủ.
Nếu cài full NeMo chưa thành công, ghi lỗi thực tế; không dùng unit test pass hoặc pip resolve để khẳng định runtime đã chạy.

## INDIVIDUAL

### VuVanDien-2A202602418

- Phần được giao và phần thực tế đã làm: Đảm nhiệm 100% toàn bộ bài lab với hình thức cá nhân. Triển khai Phase A (RAGAS 50q, bottom 10, failure matrix), Phase B (LLM judge swap-and-average, Cohen's kappa, bias analysis), Phase C (Presidio PII scanner, NeMo Guardrails self-check input/output, sequential P95 latency measurement) và Task 13 CI/CD Blueprint.
- Bằng chứng: Code tại src/m1\_chunking.py đến src/m5\_enrichment.py, src/phase\_a\_ragas.py, src/phase\_b\_judge.py, src/phase\_c\_guard.py; 4 artifacts JSON tại artifacts/; 3 báo cáo phân tích tại doc/reports/.
- Cách kiểm tra: 91/91 unit/support offline tests đạt 100% pass với pytest; script thẩm định hợp đồng scripts/check\_lab.py kiểm tra schema và logic toán học.
- Điều đã học: Hiểu sâu về đánh giá RAG đa chiều qua RAGAS; kỹ thuật triệt tiêu position bias bằng swap-and-average trong LLM-as-a-judge; đo lường độ đồng thuận qua Cohen's Kappa; cơ chế bảo vệ nhiều lớp kết hợp Presidio PII và NeMo Guardrails; và cách thiết kế CI/CD quality gate cho LLM applications.
- Giới hạn/cách xử lý: NeMo Guardrails có độ trễ P95 (3130ms) vượt budget 500ms do phụ thuộc network roundtrip tới API provider; đã đề xuất giải pháp caching và local guardrail model trong Blueprint.
- Nguồn/AI hỗ trợ nếu có: Sử dụng AI coding assistant hỗ trợ sinh mã mẫu và debug theo hướng dẫn bài lab, tự thẩm định lại toàn bộ logic bằng test suite offline và hợp đồng dữ liệu.

## Cập nhật sau khi nộp

Bản nộp ban đầu theo đúng hạn quy định, không có cập nhật sau deadline.
