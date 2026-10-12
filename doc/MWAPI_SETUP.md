# Cấu hình Claude high-speed 5x qua MWAPI

Project dùng giao thức Anthropic Messages (`POST /v1/messages`). Base URL cho
Anthropic SDK là `https://api.mwapi.dev`, **không** thêm `/v1`.

## 1. Điền `.env`

```env
LLM_API_KEY=<key MWAPI của bạn>
LLM_API_FORMAT=anthropic
LLM_BASE_URL=https://api.mwapi.dev
LLM_MODEL=<model ID chính xác trên dashboard MWAPI>
```

Không đoán model ID và không commit `.env`. Có thể xem model mà key được phép
dùng bằng:

```powershell
python scripts/check_llm.py --models
```

Lệnh này gọi endpoint danh sách model, không sinh nội dung. Chỉ lệnh `--test`
mới gửi một request generation có tính phí:

```powershell
python scripts/check_llm.py --test
```

Nếu `--models` trả `401/403`, key có thể không được MWAPI cấp quyền xem catalog.
Khi đó lấy model ID trực tiếp từ dashboard; lỗi catalog không tự động có nghĩa
endpoint `/v1/messages` cũng bị từ chối.

## 2. Khai báo đúng giá 5x

Với model hiện dùng `claude-haiku-4-5-20251001`, project ước tính theo base rate
`$1/M input`, `$5/M output` và nhân `5`, tức `$5/M input`, `$25/M output`:

```env
LLM_PRICE_MULTIPLIER=5
LLM_BASE_INPUT_USD_PER_MTOK=1
LLM_BASE_OUTPUT_USD_PER_MTOK=5
```

Phải thay hai base rate theo đúng model/bảng giá trong tài khoản MWAPI. Nếu
dashboard đã hiển thị **giá cuối cùng sau 5x**, nhập giá đó vào hai biến base và
đặt `LLM_PRICE_MULTIPLIER=1` để không nhân hai lần.

Công thức project dùng:

```text
cost = input_tokens × base_input × multiplier / 1,000,000
     + output_tokens × base_output × multiplier / 1,000,000
```

## 3. Giới hạn chi phí

Thiết lập mặc định:

```env
LLM_MAX_RUN_USD=3
LLM_MAX_DAILY_USD=5
LLM_MAX_REQUESTS=600
LLM_MAX_OUTPUT_TOKENS=512
ENABLE_LLM_ENRICHMENT=0
```

- Project dự trù chi phí trước request và chặn nếu vượt giới hạn.
- Usage thực tế từ response được ghi vào `.cache/llm_budget.json`.
- M5 bị tắt mặc định vì có thể tạo một request cho mỗi chunk.
- Các lời gọi trực tiếp, RAGAS và NeMo dùng chung bộ theo dõi trong một process.
- Đây là lớp bảo vệ cục bộ. Hãy đặt thêm hard quota khoảng `$5` cho key trên
  dashboard MWAPI vì quota phía provider mới bảo vệ được khi process bị lỗi hoặc
  có chương trình khác dùng cùng key.

Kiểm tra ledger mà không gọi API:

```powershell
python scripts/check_llm.py --budget
```

## 4. Cài dependency và chạy

```powershell
python -m pip install -r requirements/requirements.txt -c requirements/constraints-core.txt
python scripts/check_llm.py
python scripts/setup_answers.py --live
python scripts/run_experiments.py --phase a --live
```

Chạy `setup_answers.py` trước với `ENABLE_LLM_ENRICHMENT=0`. Chỉ bật enrichment
sau khi đã đếm số chunk và tăng quota một cách có chủ ý.

## Lưu ý về high-speed

Trang công khai của MWAPI không mô tả một request field riêng để bật high-speed.
Vì vậy project không tự thêm trường `speed` chưa được xác minh. Tier high-speed
phải được chọn bằng key/route/model mà dashboard MWAPI cấp; biến multiplier trong
project chỉ dùng để ước tính và chặn chi phí.
