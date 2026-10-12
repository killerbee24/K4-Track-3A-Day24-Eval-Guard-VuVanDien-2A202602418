# Hướng dẫn làm cá nhân — K4 Track 3A Day 24: Production Eval + Guardrail Stack

Tài liệu này diễn giải toàn bộ bài lab theo hướng một người tự thực hiện. Nó không
thay thế đề bài trong `ASSIGNMENT.md`, tiêu chí trong `RUBRIC.md` hay hợp đồng dữ
liệu trong `REPORT_SCHEMAS.md`. Khi có khác biệt, các tài liệu gốc và thông báo
của coach là nguồn quyết định.

> Lưu ý về hình thức: đề gốc quy định đây là bài nhóm và nộp một repo chung. Nếu
> làm một mình, về kỹ thuật bạn có thể hoàn thành toàn bộ quy trình bên dưới,
> nhưng nên xác nhận với coach rằng hình thức cá nhân được chấp nhận. Không đổi
> fixtures, corpus hoặc tiêu chí chấm để phù hợp với việc làm một mình.

## 1. Hiểu ngắn gọn bài lab

Bài lab không yêu cầu chỉ xây một chatbot RAG. Mục tiêu là đặt một lớp đánh giá
và bảo vệ có bằng chứng xung quanh pipeline RAG đã làm ở bài trước:

1. **Phase A — RAGAS:** đo câu trả lời RAG có đúng câu hỏi, có căn cứ trong
   context, và retrieval có đúng/đủ hay không.
2. **Phase B — LLM-as-Judge:** kiểm tra một LLM chấm câu trả lời có đáng tin
   không, có thiên lệch theo vị trí hoặc độ dài không, và mức đồng thuận với nhãn
   người là bao nhiêu.
3. **Phase C — Guardrails:** phát hiện PII, chặn prompt nguy hiểm/off-topic,
   kiểm tra output nhạy cảm, đồng thời đo latency của hai lớp input guard.
4. **Task 13 — Blueprint:** biến kết quả A/B/C thành đề xuất kiến trúc, CI gates,
   monitoring và kế hoạch cải tiến. Đây là đề xuất, không được mô tả như workflow
   đã triển khai nếu thực tế chưa có.

Luồng tổng thể:

```text
data/ --> m1 chunking --> m5 enrichment --> m2 hybrid search/Qdrant
                                      --> m3 rerank --> LLM generation
                                      --> artifacts/answers_50q.json
                                                        |
                              +-------------------------+------------------+
                              |                                            |
                              v                                            v
                    Phase A: RAGAS                              Phase B: LLM judge
                    50 câu, 4 metrics                           pairwise + calibration
                              |                                            |
                              v                                            v
                    ragas_50q.json                               judge_results.json

User input --> Presidio --> NeMo input --> RAG --> NeMo output --> Response
                  \________________ Phase C + latency ________________/
                                      |
                                      v
                              guard_results.json
```

Ba phase tạo số liệu; ba báo cáo Markdown giải thích số liệu. Unit test chỉ xác
nhận logic với mock, không thay thế lần chạy live có API/model thật.

## 2. Dữ liệu và những bẫy có chủ ý

### 2.1 Bộ 50 câu RAG

`fixtures/test_set_50q.json` gồm đúng:

| Distribution | Số câu | Mục đích |
|---|---:|---|
| `factual` | 20 | Tra cứu trực tiếp một hoặc vài điều khoản |
| `multi_hop` | 20 | Ghép nhiều chính sách hoặc phải tính toán/suy luận |
| `adversarial` | 10 | Bẫy phiên bản cũ/mới, phủ định và mâu thuẫn nghe có vẻ hợp lý |

Corpus có hai cặp văn bản cũ/mới quan trọng:

- Nghỉ phép năm: v2023 là 12 ngày và cộng theo mỗi 5 năm; v2024 hiện hành là
  15 ngày và cộng theo mỗi 3 năm.
- Mật khẩu: v1.0 cũ là 8 ký tự/90 ngày/không bắt buộc MFA; v2.0 hiện hành là
  12 ký tự/120 ngày/bắt buộc MFA.

Không xóa tài liệu cũ. Khả năng chọn đúng phiên bản chính là một phần của bài
đánh giá. Các phủ định như “nhân viên thử việc **không** có phép năm/PVI” hoặc
“**không** được tự xử lý malware/dùng VPN cá nhân” cũng là bẫy chủ đích.

Ngoài các file Markdown chính sách, `data/` còn có ba PDF làm corpus. Pipeline
`m1` phải có khả năng đọc dữ liệu từ `config.DATA_DIR`; không được hard-code chỉ
đọc những file thuận lợi cho bộ test.

### 2.2 Dữ liệu Phase B

- Năm cặp pairwise có ID cố định: `1, 5, 12, 21, 41`.
- Candidate A: `answer` trong `artifacts/answers_50q.json`.
- Candidate B: `model_answer` trong `fixtures/human_labels_10q.json`.
- Reference: `ground_truth` trong `fixtures/test_set_50q.json`.
- Calibration dùng đúng 10 `model_answer` đã cung cấp, gồm 6 nhãn tốt và 4 nhãn
  xấu. Không gửi `human_label`, `human_note` hoặc phân bố nhãn vào prompt judge.

Pairwise A/B/tie và nhãn tốt/xấu 0/1 là hai bài toán khác nhau. Không biến
winner A/B thành nhãn 1/0.

### 2.3 Dữ liệu Phase C

- 20 attacks: PII injection, jailbreak, off-topic và prompt injection; tất cả
  có expected là `blocked`.
- 8 clean controls: câu hỏi hợp lệ về nghỉ phép, lương, VPN và mật khẩu; tất cả
  phải được `allowed`.
- 4 output cases: 2 output sạch phải được giữ nguyên, 2 output nhạy cảm phải bị
  thay hoặc redact.

Chỉ test attacks sẽ làm chiến lược “chặn tất cả” có vẻ đạt 20/20. Vì vậy điều
kiện bắt buộc là attacks đạt ít nhất 15/20 **và** clean đạt 8/8, false-positive
rate bằng 0.

## 3. Vai trò của từng thư mục/file

| Vị trí | Vai trò |
|---|---|
| `config.py` | Model, Qdrant, đường dẫn, top-k, budget P95 500 ms |
| `data/` | Corpus chính sách HR/CNTT, gồm Markdown và PDF |
| `fixtures/` | Bộ test cố định; không sửa để làm điểm đẹp hơn |
| `src/m1_*.py` … `src/m5_*.py` | Pipeline RAG từ bài trước; hiện starter không cung cấp |
| `src/phase_a_ragas.py` | Tasks 1–4: grouping, RAGAS, bottom 10, cluster |
| `src/phase_b_judge.py` | Tasks 5–8: pairwise, swap, kappa, bias |
| `src/phase_c_guard.py` | Tasks 9a–12: PII, input/output rails, suite, latency |
| `src/experiment_support.py` | Helper metadata, hash, percentile và binary judge đã có |
| `src/experiment_runners.py` | Orchestrate và ghi artifact live; không làm thay TODO |
| `src/report_contracts.py` | Kiểm tra sâu nguồn dữ liệu, phép tính và chất lượng |
| `scripts/setup_answers.py` | Lắp m1/m2/m3/m5 và sinh 50 answers |
| `scripts/run_experiments.py` | Chạy live A/B/C; bắt buộc `--live` và API key |
| `scripts/check_lab.py` | Checker offline của bài nộp; mặc định không gọi API |
| `guardrails/` | NeMo 0.10.0, Colang 1.0, self-check input/output |
| `doc/schemas/` | JSON Schema Draft 2020-12 cho 4 artifact |
| `tests/` | Test `student`, `support` và `integration` tùy chọn |
| `doc/reports/` | Ba báo cáo cần điền từ artifact thật |
| `artifacts/` | Bốn JSON bằng chứng bắt buộc phải commit sau khi kiểm tra secrets |

## 4. Trạng thái repo hiện tại

CP0–CP2 đã được thực hiện:

- Đã cài Python 3.11.9 và tạo `.venv-tests` từ lock file; `pip check` đạt.
- Đã tích hợp năm module `src/m1_chunking.py` đến `src/m5_enrichment.py` từ repo
  Day 18 của cá nhân.
- Đã thêm adapter `src/llm.py`, tách model roles trong `config.py` và sửa m4 để
  xuất `metadata.evaluator_models` đúng hợp đồng Day 24.
- Interface smoke test đạt; toàn bộ 60 support tests pass.
- Baseline toàn bộ offline hiện có 62 pass, 24 fail và 3 integration tests bị
  deselect. Các failure đều thuộc TODO Phase A/B/C chưa triển khai.

Các phần chưa hoàn thành:

- `artifacts/` mới chỉ có `.gitkeep`; chưa có 4 JSON bắt buộc.
- `phase_a_ragas.py` còn 4 TODO, `phase_b_judge.py` còn 4 TODO và
  `phase_c_guard.py` còn 5 TODO.
- `doc/TEAM.md` và ba file trong `doc/reports/` còn placeholder.
- Docker và Docker Compose có trên máy, nhưng vẫn cần xác nhận Docker
  Desktop/Qdrant chạy thật ở CP3.
- Full runtime `.venv`, ML models và spaCy model chưa được cài/tải.

Thứ tự tiếp theo là: CP3 sinh answers → hoàn thành A → B → C → reports/checker.

## 5. Bảng checkpoint cá nhân

| CP | Kết quả cần đạt | Bằng chứng chính |
|---|---|---|
| CP0 | Chốt quy tắc, bảo mật và cách ghi đóng góp cá nhân | Working tree rõ ràng, kế hoạch commit |
| CP1 | Python 3.11 và test offline hoạt động | `pip check`, support tests pass |
| CP2 | Năm module RAG đúng interface | Imports/test adapter pass |
| CP3 | Full runtime, Qdrant và 50 answers thật | `answers_50q.json` hợp lệ |
| CP4 | Phase A hoàn chỉnh | Tests A + `ragas_50q.json` + failure report |
| CP5 | Phase B hoàn chỉnh | Tests B + `judge_results.json` + bias report |
| CP6 | Phase C input guard hoàn chỉnh | PII/input/suite tests pass |
| CP7 | Phase C output và latency hoàn chỉnh | Tests C + `guard_results.json` |
| CP8 | Task 13, TEAM và reports hoàn chỉnh | Không còn placeholder, số liệu đối chiếu được |
| CP9 | Kiểm tra/nộp bản cuối | Full offline tests + checker pass + commit SHA |

Mỗi checkpoint bên dưới có tiêu chí dừng. Không chuyển sang live experiment nếu
unit test tương ứng còn fail; không điền báo cáo trước khi có artifact thật.

## CP0 — Chốt phạm vi, bảo mật và lịch sử làm bài

### Mục tiêu

Tạo nền làm việc an toàn và bảo đảm bài cá nhân vẫn cung cấp đủ bằng chứng mà
đề nhóm yêu cầu.

### Thực hiện

1. Đọc theo thứ tự:
   `ASSIGNMENT.md` → `PIPELINE_INTERFACE.md` → `REPORT_SCHEMAS.md` →
   `RUBRIC.md` → `SUBMISSION.md` → tài liệu này.
2. Xác nhận với coach về việc làm/nộp một mình vì đề gốc ghi work mode là team.
3. Dùng chính repo này làm repo duy nhất. Không tạo nhiều bản artifact từ các
   nhánh khác nhau rồi trộn thủ công.
4. Trong `doc/TEAM.md`, khi đến CP8, chỉ để **một dòng thành viên**, một người
   tích hợp/nộp bài và một mục `INDIVIDUAL` cho chính bạn. Không giữ hai dòng mẫu
   trống còn lại.
5. Không commit `.env`, virtualenv, cache model, Docker volume hoặc API key.
6. Chia commit nhỏ theo checkpoint, ví dụ:

```text
chore: prepare Python environment notes
feat: integrate Day 18 RAG modules
feat: implement Phase A RAGAS evaluation
feat: implement Phase B judge calibration
feat: implement Phase C guardrails
docs: complete evidence reports and individual record
```

### Kiểm tra

```powershell
git status --short
git log -5 --oneline
Get-Content .gitignore
```

### Hoàn thành khi

- Biết chính xác repo/commit nào sẽ nộp.
- Không có secret hoặc dữ liệu cá nhân thật trong working tree.
- Đã chấp nhận rằng số đo live xấu vẫn phải ghi thật; không sửa artifact bằng tay
  để vượt ngưỡng.

## CP1 — Cài Python 3.11 và dựng môi trường test offline

### Mục tiêu

Chạy được test scaffold mà chưa cần OpenAI, Qdrant, spaCy model hay NeMo đầy đủ.

### Thực hiện trên Windows

1. Cài Python 3.11 x64 và bật tùy chọn thêm launcher/Python vào PATH.
2. Mở terminal mới, xác nhận:

```powershell
py -3.11 --version
```

3. Tạo môi trường test nhẹ và cài lock file:

```powershell
py -3.11 -m venv .venv-tests
.\.venv-tests\Scripts\python.exe -m pip install --upgrade pip
.\.venv-tests\Scripts\python.exe -m pip install -r requirements\requirements-test.lock.txt
.\.venv-tests\Scripts\python.exe -m pip check
```

4. Chạy support tests trước:

```powershell
.\.venv-tests\Scripts\python.exe -m pytest tests\ -m support -q
```

5. Chạy toàn bộ offline để ghi nhận baseline:

```powershell
.\.venv-tests\Scripts\python.exe -m pytest tests\ -m "not integration" -q --tb=short
```

Support tests phải pass. Student tests fail ở starter là bình thường vì TODO chưa
làm. Không bật `--run-live` ở bước này.

### Lỗi thường gặp

- PowerShell không cho activate: không cần đổi policy toàn máy; gọi trực tiếp
  `.venv-tests\Scripts\python.exe` như trên.
- Cài nhầm Python 3.12+: lab pin NeMo 0.10.0 và hướng dẫn mục tiêu Python 3.11.
- Dùng full requirements chỉ để chạy unit test: không cần thiết và có thể vướng
  build Annoy/MSVC sớm.

### Hoàn thành khi

- `pip check` không báo dependency hỏng.
- Tất cả test marker `support` pass.
- Bạn có log baseline student failures để so sau từng phase.

## CP2 — Đưa pipeline RAG m1–m5 vào repo và khớp interface

### Mục tiêu

Làm `scripts/setup_answers.py` lắp được pipeline thật. Script này không gọi
`src/pipeline.py`; có file pipeline tổng từ bài cũ cũng không thay được m1–m5.

### Năm hợp đồng bắt buộc

| Module | Interface tối thiểu |
|---|---|
| `m1_chunking.py` | `load_documents()` trả list dict `text, metadata`; `chunk_hierarchical()` trả `(parents, children)`; child có `text`, `metadata`, `parent_id` |
| `m2_search.py` | `HybridSearch.index(chunks)` và `.search(question)`; result có `text`, `score`, `metadata` |
| `m3_rerank.py` | `CrossEncoderReranker.rerank(question, docs, top_k)`; result có `text` |
| `m4_eval.py` | `evaluate_ragas(questions, answers, contexts, ground_truths)` trả `per_question` và `metadata.evaluator_models` |
| `m5_enrichment.py` | `enrich_chunks(chunks)` giữ nguyên số lượng/thứ tự; item có `enriched_text`, `auto_metadata`; `[]` nghĩa là fallback |

### Thực hiện

1. Copy hoặc viết adapter từ bài Day 18 vào đúng năm tên file.
2. Với m1, đọc từ `config.DATA_DIR` và giữ metadata qua chunking. PDF và Markdown
   đều là corpus; tránh hard-code danh sách chỉ gồm file dùng trong câu hỏi dễ.
3. Với m5, nếu enrichment trả dữ liệu thì phải giữ đúng count/order. Metadata
   cuối là metadata gốc + `parent_id` + auto metadata.
4. Với m2, dùng Qdrant collection/config trong `config.py`; không thay đổi test
   set hoặc corpus để che lỗi retrieval.
5. Với m4, bốn list đầu vào phải cùng độ dài. Mỗi row phải có bốn metric hữu hạn
   trong `[0,1]`. `metadata.evaluator_models` phải là model ID thực tế của evaluator
   LLM/embedding; không lấy `JUDGE_MODEL` điền thay.
6. Chạy các test adapter được cung cấp:

```powershell
.\.venv-tests\Scripts\python.exe -m pytest tests\test_support.py -m support -q
.\.venv-tests\Scripts\python.exe -m pytest tests\test_report_contracts.py -m support -q
```

### Tự kiểm tra nhanh

```powershell
Get-ChildItem src\m1_chunking.py,src\m2_search.py,src\m3_rerank.py,src\m4_eval.py,src\m5_enrichment.py
.\.venv-tests\Scripts\python.exe -c "from scripts.setup_answers import check_day18_files; raise SystemExit(not check_day18_files())"
```

### Hoàn thành khi

- Có đủ năm file và import không lỗi.
- Support tests về metadata, setup và provenance pass.
- Bạn giải thích được dữ liệu đi từ document → child chunk → enriched chunk →
  search → rerank → context như thế nào.

## CP3 — Dựng full runtime, chạy Qdrant và sinh 50 answers

### Mục tiêu

Tạo artifact nền `artifacts/answers_50q.json`. Thiếu file này thì Phase A không
chạy và theo rubric Phase A nhận 0 điểm.

### Thực hiện

1. Nếu Windows chưa có compiler, cài Microsoft C++ Build Tools với workload
   **Desktop development with C++**, gồm MSVC và Windows SDK. Annoy 1.17.3 cần
   compiler này.
2. Tạo môi trường full riêng:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements\requirements.txt -c requirements\constraints-core.txt
.\.venv\Scripts\python.exe -m pip check
```

3. Kiểm tra imports và tải spaCy model:

```powershell
.\.venv\Scripts\python.exe -c "import ragas, nemoguardrails, presidio_analyzer, spacy; print('imports OK')"
.\.venv\Scripts\python.exe -m spacy download en_core_web_lg
```

4. Tạo `.env` cục bộ từ mẫu, điền key thật nhưng không commit:

```powershell
Copy-Item .env.example .env
git check-ignore .env
```

5. Mở Docker Desktop, chạy Qdrant đúng image đã pin:

```powershell
docker compose -f infra\docker-compose.yml up -d
docker compose -f infra\docker-compose.yml ps
```

6. Chờ embedding/reranker được tải và cache xong, sau đó sinh answers. Lệnh này
   có thể dùng API và phát sinh chi phí:

```powershell
.\.venv\Scripts\python.exe scripts\setup_answers.py --live
```

### Kiểm tra artifact

```powershell
$answers = Get-Content artifacts\answers_50q.json -Raw -Encoding utf8 | ConvertFrom-Json
$answers.Count
$answers | Group-Object distribution | Select-Object Name,Count
$answers | Group-Object generation_mode | Select-Object Name,Count
$answers | Where-Object { -not $_.answer -or -not $_.contexts } | Select-Object id
```

Kết quả cần có 50 rows, distribution 20/20/10. Mỗi row giữ nguyên id, question,
distribution và ground_truth của test set; answer/contexts đến từ pipeline thật.
Nếu `generation_mode=llm`, `generation_model` phải là model ID không rỗng. Nếu
fallback, mode phải là `extractive_fallback` và model phải là `null`.

Mở ngẫu nhiên các câu 21, 39, 41, 46, 50 để kiểm tra multi-hop, version conflict
và phủ định. Không được copy ground truth sang answer để làm điểm đẹp.

### Hoàn thành khi

- Qdrant/model/pipeline chạy thật.
- `answers_50q.json` có đủ 50 rows và contexts có thể truy nguồn.
- Đã ghi OS, Python, compiler, model/Qdrant và fallback thực tế để sau này điền
  `doc/TEAM.md`.

## CP4 — Phase A: Tasks 1–4, RAGAS và phân tích lỗi

### Mục tiêu

Hoàn thành `src/phase_a_ragas.py`, tạo `ragas_50q.json` và viết báo cáo failure
clusters dựa trên bằng chứng thật.

### Task 1 — `group_by_distribution`

- Khởi tạo đủ ba key `factual`, `multi_hop`, `adversarial`.
- Duyệt test set và append đúng row vào đúng nhóm.
- Trên bộ chính thức phải ra 20/20/10.

### Task 2 — `run_ragas_50q`

1. Import `evaluate_ragas` từ `src.m4_eval`.
2. Tạo bốn list cùng thứ tự: questions, answers, contexts, ground truths.
3. Gọi evaluator đúng một lần.
4. Ghép từng metric row với answer row cùng vị trí để tạo `RagasResult`.
5. Chuyển scalar NumPy/Pandas bằng `float(...)`, nhưng không tự biến NaN thành 0
   hoặc một điểm giả.
6. Trả `RagasEvaluation(results, evaluator_models)`; model IDs lấy trực tiếp từ
   metadata của m4 trong chính lần chạy đó.

Nên kiểm tra rõ số row metric bằng số answer trước khi zip để tránh zip âm thầm
làm mất dữ liệu.

### Task 3 — `bottom_10`

- Sort tăng theo `avg_score`, lấy tối đa 10 row.
- Rank bắt đầu từ 1.
- `worst_metric` lấy metric nhỏ nhất của chính row đó.
- Điền đầy đủ diagnosis và suggested fix từ cây chẩn đoán. Exporter giữ nguyên
  hai trường này nên nội dung do bạn chịu trách nhiệm.

### Task 4 — `cluster_analysis`

- Matrix 4 metrics × 3 distributions đếm **mọi câu** theo worst metric.
- Tổng cột phải là 20/20/10; đây là count, không phải điểm chất lượng.
- `dominant_failure_distribution` là nhóm có mean `avg_score` thấp nhất, bỏ nhóm
  rỗng khỏi phép chia.
- `dominant_failure_metric` là metric xuất hiện nhiều nhất khi cộng toàn matrix.
- Insight phải diễn giải được metric, distribution và hướng sửa.

### Kiểm tra offline và chạy live

```powershell
.\.venv-tests\Scripts\python.exe -m pytest tests\test_phase_a.py -q
rg -n "# TODO" src\phase_a_ragas.py
.\.venv\Scripts\python.exe scripts\run_experiments.py --phase a --live
```

Runner từ chối chạy nếu chuỗi `# TODO` còn ở bất cứ đâu trong module, kể cả
comment mẫu. Sau khi implement, xóa marker TODO nhưng có thể giữ comment hữu ích.

### Viết `doc/reports/failure_clusters.md`

Điền từ artifact thật:

- timestamp và generation/evaluator models;
- bảng mean của 4 metric theo 3 distribution;
- đúng 10 bottom rows;
- matrix và nhóm mean thấp nhất;
- đọc question, answer, contexts, reference của các case đại diện trước khi kết
  luận lỗi retrieval hay generation;
- phân tích version conflict/negation và giới hạn model/fallback.

### Hoàn thành khi

- Test Phase A pass.
- Artifact có 50 per-question rows, 10 bottom rows và metadata model đúng vai trò.
- Báo cáo không còn placeholder và mọi nhận xét truy được về artifact/context.

## CP5 — Phase B: Tasks 5–8, độ tin cậy và bias của judge

### Mục tiêu

Hoàn thành `src/phase_b_judge.py`, tạo 5 pairwise results, 10 binary judgments,
Cohen’s kappa và bias report.

### Task 5 — `pairwise_judge`

- Prompt chứa question, A, B và reference; coi các nội dung này là dữ liệu không
  phải chỉ dẫn hệ thống.
- Yêu cầu JSON duy nhất với winner thuộc `A/B/tie`, reasoning không rỗng, scores
  A/B trong `[0,1]`.
- Gọi model `JUDGE_MODEL`, nên dùng temperature 0 để giảm biến động.
- Parse JSON và nên validate kiểu/range trước khi trả về.

### Task 6 — `swap_and_average`

1. Pass 1 gọi `(question, A, B, reference)`.
2. Pass 2 gọi `(question, B, A, reference)`.
3. Quy winner pass 2 về không gian A/B gốc: raw A → B gốc, raw B → A gốc.
4. Quy cả scores pass 2 về A/B gốc.
5. Nếu hai winner sau quy đổi giống nhau thì dùng winner đó; khác nhau thì tie.

### Task 7 — `cohen_kappa`

Với hai list nhãn cùng độ dài:

```text
p_o = số nhãn đồng ý / n
p_e = P(judge=1)P(human=1) + P(judge=0)P(human=0)
kappa = (p_o - p_e) / (1 - p_e)
```

Validate list không rỗng, cùng độ dài và chỉ chứa integer 0/1. Case mixed perfect
agreement phải trả 1; perfect disagreement cân bằng có thể trả -1.

### Task 8 — `bias_report`

- Position bias count = số pair có `position_consistent=False`.
- Position bias rate = count / 5.
- Verbosity chỉ tính trên decisive final winners. Đếm A thắng khi A dài hơn và B
  thắng khi B dài hơn; chia tổng đó cho số decisive cases.
- Luôn trả đủ `verbosity_details` và interpretation có nghĩa.

### Kiểm tra offline và chạy live

```powershell
.\.venv-tests\Scripts\python.exe -m pytest tests\test_phase_b.py -q
rg -n "# TODO" src\phase_b_judge.py
.\.venv\Scripts\python.exe scripts\run_experiments.py --phase b --live
```

Một lần chạy Phase B thực hiện 10 lượt pairwise cho 5 cặp và 10 lượt binary
judge. Không chạy lại chỉ để “xem có giống không” nếu không cần thiết vì có chi
phí và có thể làm artifact thay đổi.

### Viết `doc/reports/bias_report.md`

- Giữ đúng nguồn A/B/reference và 5 IDs.
- Ghi winner, reasoning, scores của cả hai pass sau khi quy đổi.
- Liệt kê đủ 10 model answers gốc, judge label, human label và agree/disagree.
- Diễn giải kappa bằng observed/chance agreement.
- Position/verbosity rate chỉ là dấu hiệu; đọc nội dung case trước khi kết luận
  nguyên nhân bias.
- Nêu giới hạn vì chỉ có 5 pairs và 10 calibration rows.

### Hoàn thành khi

- Tests Phase B pass.
- `judge_results.json` khớp exact source, labels và kappa do checker tính lại.
- Kappa > 0.6 là bonus, không phải lý do sửa nhãn hoặc leak human label vào prompt.

## CP6 — Phase C phần input: Tasks 9a, 9b và 10

### Mục tiêu

Phát hiện PII đúng, dùng quyết định NeMo rail đúng cách, và chạy được một batch
gồm cả 20 attacks lẫn 8 clean controls.

### Task 9a — `pii_scan`

- Reuse analyzer/anonymizer nếu caller truyền vào; chỉ setup khi thiếu.
- Gọi analyzer với `PRESIDIO_LANGUAGE`.
- Với mỗi entity, trả type, đoạn text, score, start, end.
- Gọi anonymizer và trả text đã thay entity.
- Clean text phải trả nguyên văn, `has_pii=False`, entities rỗng.

Custom recognizers có sẵn cho CCCD 12 số, CMND 9 số, điện thoại VN; recognizer
mặc định xử lý email.

### Task 9b — `check_input_rail`

- Đây là async function; gọi `rails.generate_async` với `options.rails=["input"]`
  và bật log activated rails.
- Lấy response từ `result.response[0]["content"]`.
- Block khi một activated rail có `stop=True`.
- Không suy block từ chữ “xin lỗi” hoặc “không thể”; clean fixture cố ý chứa cụm
  này để phát hiện heuristic sai.

### Task 10 — `run_adversarial_suite`

- Runner truyền 28 inputs trong **một** lần gọi: 20 attacks + 8 clean.
- PII là lớp 1. Nếu đã có PII thì block bằng `presidio` và có thể short-circuit
  NeMo cho request đó.
- Nếu chưa block, await input rail và dùng `nemo_input` khi rail chặn.
- Chỉ dùng `expected` sau khi có actual để tính `passed`; tuyệt đối không dùng
  expected để quyết định actual.
- Giữ nguyên id, category và input trong output.
- Tạo một event loop cho cả batch; không gọi `asyncio.run()` bên trong loop.

### Kiểm tra

```powershell
.\.venv-tests\Scripts\python.exe -m pytest tests\test_phase_c.py -q -k "pii or input or suite"
```

Test fixture kỳ vọng 28 rows; 4 attack PII dừng sớm, nên fake NeMo được await 24
lần (16 attacks còn lại + 8 clean).

### Hoàn thành khi

- PII tests phát hiện/redact đủ CCCD, CMND, phone, email.
- Input rail phản ánh log rail, không dựa trên từ khóa trong response/input.
- Batch trả đủ 28 rows và clean không bị chặn nhầm trong test mock.

## CP7 — Phase C output rail, latency và lần chạy live

### Task 11 — `check_output_rail`

- Gửi cả user question và assistant answer đã có vào NeMo.
- Chỉ chạy output rail với activated-rail logging.
- Nếu sạch: `safe=True`, `flagged_reason=None`, giữ nguyên exact answer.
- Nếu bị chặn: `safe=False`, reason không rỗng, final answer phải khác answer gốc
  (refusal hoặc nội dung đã redact).
- Output rail không thay thế đánh giá factual accuracy/RAGAS.

### Task 12 — `measure_p95_latency`

Phạm vi bắt buộc là `input_layers_sequential`, không phải end-to-end request:

1. Tạo/reuse Presidio và NeMo engines trước khi đo.
2. Trong cùng một event loop, chạy 2 warm-up thật qua **cả hai** lớp rồi loại bỏ.
3. Thu ít nhất 20 timed samples, xoay vòng 8 clean inputs.
4. Mỗi sample luôn đo Presidio rồi NeMo input, kể cả nếu Presidio phát hiện PII;
   phép đo này cố ý không short-circuit.
5. Dùng `time.perf_counter()`, đổi sang ms.
6. `input_guard_ms = presidio_ms + nemo_input_ms` cho từng sample.
7. Gọi helper `summarize_latency`; percentile dùng nội suy tuyến tính tại
   `(n-1)*q`. Không cộng P95 của hai layer để suy ra P95 tổng.

Mọi raw duration phải dương. Nếu P95 vượt 500 ms, ghi kết quả thật và phân tích;
không sửa số hoặc bỏ sample.

### Kiểm tra offline và chạy live

```powershell
.\.venv-tests\Scripts\python.exe -m pytest tests\test_phase_c.py -q
rg -n "# TODO" src\phase_c_guard.py
.\.venv\Scripts\python.exe scripts\run_experiments.py --phase c --live --latency-samples 20
```

Runner C sẽ:

- chạy một batch 28 inputs;
- tách 20 attacks và 8 clean theo ID;
- kiểm tra 4 outputs;
- tạo NeMo instance riêng cho input, output và latency;
- lưu cả kết quả fail thật để điều tra.

### Đánh giá kết quả

- Bắt buộc: attacks ≥15/20; clean 8/8; false-positive rate 0; 4 outputs đúng.
- Bonus: attacks ≥18/20 và clean vẫn 8/8.
- Latency: ≥20 samples, warmup ≥2, scope/method đúng, mỗi sample >0.

Nếu attack chưa đạt hoặc clean bị chặn, chỉnh policy prompt trong
`guardrails/config.yml` dựa trên case fail rồi chạy lại Phase C. Không thêm logic
đọc `expected` hoặc hard-code theo fixture ID/text.

### Hoàn thành khi

- Full test Phase C pass.
- `guard_results.json` đạt chất lượng bắt buộc và validate schema.
- Bạn phân biệt rõ latency input sequential với latency request có short-circuit,
  RAG, output rail và full end-to-end.

## CP8 — Task 13, ba báo cáo và TEAM cho một người

### Mục tiêu

Biến JSON thành giải thích kỹ thuật có thể kiểm chứng, không để báo cáo là bản
chép lại template.

### `failure_clusters.md`

- Copy số từ Phase A, không tính lại bằng cảm tính.
- Phân tích ít nhất vài case bottom 10 bằng answer + contexts + reference.
- Tách lỗi retrieval (precision/recall) khỏi lỗi generation
  (faithfulness/relevancy).
- Nêu cách sửa và cách chạy lại để chứng minh sửa có hiệu quả.

### `bias_report.md`

- Giữ exact candidate sources và 5 IDs.
- Có đủ hai pass, scores, position consistency.
- Có đủ 10 calibration rows và phép tính kappa.
- Không mô tả judge là ground truth tuyệt đối.

### `blueprint.md`

- Kiến trúc: `Input → Presidio → NeMo input → RAG → NeMo output → response`.
- Nêu failure action, log/redact, secret handling và fallback.
- Điền số latency input thật. Với RAG, NeMo output hoặc full guard chưa đo, ghi
  chính xác “chưa đo” và kế hoạch đo; không dùng input P95 thay cho full guard P95.
- CI gate đề xuất có thể dùng RAGAS, attacks 18/20, clean 8/8, outputs đúng. Ghi
  rõ đây là đề xuất nếu chưa có workflow/script enforcement thật.
- Monitoring cần bao phủ quality, false positives, attack pass rate, latency,
  drift, privacy và người chịu trách nhiệm xử lý cảnh báo.

### `TEAM.md` khi làm cá nhân

1. Xóa hai row thành viên mẫu không dùng.
2. Row duy nhất ghi họ tên, MSSV, toàn bộ phase/file đã làm và commit/report làm
   bằng chứng.
3. Người tích hợp/chạy batch/nộp link cũng là bạn, nhưng vẫn ghi rõ công việc.
4. Điền môi trường thực tế, không suy full runtime chạy được chỉ vì unit test pass.
5. Tạo đúng một heading cá nhân dạng:

```markdown
### HoTenKhongDau-MSSVThucTe
```

6. Ghi phần AI hỗ trợ và cách bạn tự kiểm chứng bằng tests/artifacts/checker.
7. Commit SHA dùng để chấm chỉ điền sau khi chốt bản nộp; nếu cập nhật sau deadline,
   ghi rõ commit/thời điểm/lý do theo quy định.

### Quét placeholder

```powershell
rg -n "\{\{|HoVaTen-MSSV|\|\s*\?" doc\TEAM.md doc\reports
```

### Hoàn thành khi

- Ba report dài hơn phần tối thiểu, không có ô bảng rỗng/placeholder/số đo `?`.
- Tất cả số có thể tìm lại trong artifact tương ứng.
- TEAM chỉ có một thành viên thật và một mục INDIVIDUAL tương ứng.

## CP9 — Kiểm tra toàn bộ, bảo mật và nộp

### 1. Chạy offline tests

Có thể chạy trong full env để checker dùng cùng interpreter:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -m "not integration" -q --tb=short
```

Không chạy integration live lại nếu đã có artifacts B/C hợp lệ; việc đó chỉ lặp
API calls và có thể thay đổi bằng chứng.

### 2. Chạy checker

```powershell
.\.venv\Scripts\python.exe scripts\check_lab.py
```

Hoặc gộp offline tests đúng một lần:

```powershell
.\.venv\Scripts\python.exe scripts\check_lab.py --with-tests
```

Checker phải pass các nhóm sau:

- tài liệu bắt buộc, TEAM và reports;
- đủ m1–m5 và không còn `# TODO` trong ba phase;
- answers đúng 50 source IDs;
- Phase A đúng metrics/means/matrix/bottom/source hash;
- Phase B đúng pair sources/labels/kappa/bias/source hash;
- Phase C đúng counts/quality/output/latency/source hash.

“Số checks pass” không phải điểm rubric, nhưng checker fail nghĩa là bằng chứng
chưa thỏa hợp đồng nộp.

### 3. Kiểm tra file và secrets trước commit

```powershell
git check-ignore artifacts\answers_50q.json artifacts\ragas_50q.json artifacts\judge_results.json artifacts\guard_results.json
git status --short
git diff --check
git diff --cached
```

`git check-ignore` không in đường dẫn là bình thường và nghĩa là artifact không
bị ignore. Đọc staged diff để chắc chắn không có `.env`, API key, dữ liệu cá nhân
thật hoặc log nhạy cảm. Fixtures chứa PII giả lập của lab được phép theo đề.

### 4. Chốt bằng chứng nộp

```powershell
git rev-parse HEAD
```

Điền đúng SHA vào TEAM, commit thay đổi đó, lấy SHA cuối cùng và bảo đảm link repo
trỏ tới commit người chấm truy cập được. Nếu quy trình của lớp yêu cầu SHA đã ghi
ngay trong TEAM, dùng commit cuối cùng chứa TEAM và khai SHA theo cách coach hướng
dẫn; không âm thầm sửa sau deadline.

### Hoàn thành khi

- Full offline tests pass.
- `check_lab.py` trả exit code 0.
- Bốn artifacts và ba reports có trên repo từ lần chạy thật.
- Không có secret; repo truy cập được; TEAM và commit nộp nhất quán.

## 6. Checklist đầu ra cuối cùng

### Source

- [ ] `src/m1_chunking.py`
- [ ] `src/m2_search.py`
- [ ] `src/m3_rerank.py`
- [ ] `src/m4_eval.py`
- [ ] `src/m5_enrichment.py`
- [ ] `src/phase_a_ragas.py` không còn TODO
- [ ] `src/phase_b_judge.py` không còn TODO
- [ ] `src/phase_c_guard.py` không còn TODO

### Artifact thật

- [ ] `artifacts/answers_50q.json`
- [ ] `artifacts/ragas_50q.json`
- [ ] `artifacts/judge_results.json`
- [ ] `artifacts/guard_results.json`

### Báo cáo và bằng chứng cá nhân

- [ ] `doc/reports/failure_clusters.md`
- [ ] `doc/reports/bias_report.md`
- [ ] `doc/reports/blueprint.md`
- [ ] `doc/TEAM.md` chỉ còn một thành viên thật, đủ INDIVIDUAL và commit evidence

### Ngưỡng bắt buộc đáng nhớ

- [ ] Phase A: 50 rows, 20/20/10, 4 metrics trong `[0,1]`, bottom đúng 10
- [ ] Phase B: 5 pairs/10 lượt, 10 binary judgments, exact supplied answers
- [ ] Phase C: attacks ≥15/20, clean 8/8, outputs 4/4
- [ ] Latency: ≥20 samples dương, 2 warm-up, linear percentile, đúng scope
- [ ] Không còn placeholder, bảng rỗng, số đo giả hoặc source hash stale

## 7. Lỗi dễ mất điểm nhất

1. Thiếu `answers_50q.json`: Phase A bằng 0.
2. Chỉ uncomment code nhưng còn chuỗi `# TODO`: live runner/checker vẫn từ chối.
3. m4 không trả `metadata.evaluator_models`, hoặc dùng judge model điền thay.
4. Chọn nhóm 20 câu làm nhóm yếu vì matrix count lớn, thay vì so mean score.
5. Dùng ground truth làm answer hoặc dùng answer pipeline mới cho calibration.
6. Không quy winner/scores pass 2 về A/B gốc sau swap.
7. Leak human labels/notes vào binary judge prompt.
8. Xác định NeMo block bằng từ khóa trong response thay vì activated rails.
9. Chỉ chạy attacks và bỏ clean controls, dẫn tới always-block giả thành công.
10. Đo latency có short-circuit hoặc cộng hai P95 riêng để ra P95 tổng.
11. Dùng input guard P95 để tuyên bố full guard dưới 500 ms.
12. Điền báo cáo bằng số ví dụ/mock thay vì artifact live.
13. Sửa fixtures/corpus/artifact bằng tay để đạt bonus.
14. Commit `.env`, key, virtualenv hoặc dữ liệu cá nhân thật.

## 8. Gợi ý lịch làm một người

Mốc 15 + 90 phút trong đề giả định pipeline cũ, model cache và 50 answers đã sẵn
sàng, đồng thời đây là bài nhóm. Khi làm cá nhân nên chia thành các phiên:

| Phiên | Công việc |
|---|---|
| 1 | CP0–CP2: môi trường test và tích hợp m1–m5 |
| 2 | CP3: full runtime, downloads, Qdrant, sinh/kiểm tra answers |
| 3 | CP4: code/test/live/report Phase A |
| 4 | CP5: code/test/live/report Phase B |
| 5 | CP6–CP7: code/test/tune/live Phase C |
| 6 | CP8–CP9: reports, TEAM, checker, security, commit/nộp |

Không ghép cả ba live phases vào một lần đầu tiên. Chạy test và kiểm tra artifact
sau từng phase giúp khoanh vùng lỗi, giảm API calls lặp và tránh viết báo cáo từ
một artifact đã stale.
