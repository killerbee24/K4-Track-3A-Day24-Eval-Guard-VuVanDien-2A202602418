# Đánh giá LLM Judge Phase B

Nhóm: K4-Track-3A-VuVanDien

Người phụ trách: Vũ Văn Điền - MSSV: 2A202602418

Nguồn: `artifacts/judge_results.json`; run timestamp: 2026-10-12T13:14:29.488055+00:00.
Models generation/judge: generation: ["claude-haiku-4-5-20251001"] và judge: ["claude-haiku-4-5-20251001"].

## Năm cặp A/B và hai lượt

Nguồn cố định: A từ `artifacts/answers_50q.json:answer`; B từ `fixtures/human_labels_10q.json:model_answer`; reference từ `fixtures/test_set_50q.json:ground_truth`.
Ids: 1, 5, 12, 21, 41. Không đổi nguồn sau khi xem kết quả judge.

| ID | Candidate A | Candidate B | Winner P1 | Winner P2 | Final | Position Consistent | Scores P1 (A/B) | Scores P2 (A/B) |
|---|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | Dựa trên context: Nhân viên được nghỉ **3 ngày làm việc** khi kết hôn, và không trừ vào phép năm. | Nhân viên được nghỉ 3 ngày làm việc có lương khi kết hôn. | A | A | A | True | 0.95 / 0.80 | 0.95 / 0.75 |
| 5 | Mua thiết bị trị giá 55 triệu VNĐ cần phê duyệt từ: 1. Giám đốc phòng ban... 2. Phòng CNTT... | Cần Giám đốc phòng ban phê duyệt. | B | A | tie | False | 0.25 / 0.95 | 0.75 / 0.15 |
| 12 | Thưởng Tết tối thiểu cho nhân viên chính thức có từ 6 tháng trở lên là 1 tháng lương. | Nhân viên được thưởng Tết tối thiểu 1 tháng lương. | A | tie | tie | False | 0.95 / 0.75 | 0.95 / 0.95 |
| 21 | Phép cơ bản: 15 ngày, thâm niên 9 năm: +3 ngày (Tổng 18 ngày). Lương: Không tìm thấy... | Được nghỉ 18 ngày phép (15 cơ bản + 3 thâm niên). Lương Senior từ 20 đến 35 triệu. | B | B | B | True | 0.65 / 0.95 | 0.65 / 0.95 |
| 41 | Dựa trên context, nhân viên chính thức được hưởng **15 ngày phép năm** có lương. | Nhân viên được nghỉ 12 ngày phép năm. | A | A | A | True | 0.95 / 0.15 | 0.95 / 0.20 |

Position bias count/rate: count = 2, rate = 0.40 (40.0%).
Verbosity win rate: 0.667 (66.7%); decisive cases: 3 (tổng số decisive cases: 3, số ca A dài hơn và thắng: 2, số ca B dài hơn và thắng: 0).

### Phân tích hiện tượng Bias và nguyên nhân

1. **Position Bias (Thiên lệch vị trí):** Có 2/5 cặp (Q5 và Q12) không nhất quán khi tráo đổi thứ tự `(A, B)` và `(B, A)`.
   - Tại câu 5, ở lượt 1 khi Candidate B đứng thứ hai, Judge nhận thấy B ngắn gọn và trực tiếp nên chọn B. Nhưng ở lượt 2 khi vị trí đảo ngược, Judge lại chọn phương án ở vị trí đối diện do độ dài và cách diễn giải chi tiết của A đánh lừa sự chú ý của mô hình. Kỹ thuật `swap-and-average` đã phát huy tác dụng triệt để khi hạ kết quả xuống `tie`, ngăn ngừa việc thiên vị vị trí ảnh hưởng đến kết luận cuối cùng.
   - Tại câu 12, nội dung hai câu trả lời tương đương nhau về mốc "1 tháng lương". Lượt 1 thiên về câu dài hơn (A), lượt 2 chấm hòa (`tie`), quy đổi chung thành `tie`.
2. **Verbosity Bias (Thiên lệch độ dài):** Trong 3 trường hợp có kết quả thắng phân định dứt khoát (Decisive: Q1, Q21, Q41):
   - Q1 và Q41: Candidate A dài hơn và giành chiến thắng (tỷ lệ 2/3 = 66.7%). Tuy nhiên, lý do A thắng ở đây là do chất lượng thông tin thực chất: Q1 bổ sung chi tiết "không trừ vào phép năm", Q41 chọn đúng chính sách v2024 (15 ngày) thay vì v2023 (12 ngày).
   - Q21: Candidate B ngắn hơn nhưng đầy đủ cả 2 vế (phép năm và khoảng lương Senior), trong khi A thiếu dữ kiện lương nên B thắng xứng đáng.
   - Kết luận: Dấu hiệu thống kê 66.7% nghiêng về câu dài, nhưng khi đối chiếu nội dung, nguyên nhân quyết định vẫn là tính đầy đủ (completeness) và tính chuẩn xác (accuracy) của thông tin.

## Calibration đúng model_answer

Đánh giá 10 câu chuẩn theo `fixtures/human_labels_10q.json` sử dụng binary judge:

| ID | Câu hỏi | Model Answer gốc | Judge Label | Human Label | Agree | Tóm tắt Reasoning của Judge |
|---|---|---|:---:|:---:|:---:|---|
| 1 | Nghỉ kết hôn | Nghỉ 3 ngày làm việc có lương khi kết hôn. | 1 | 1 | True | Chính xác về số ngày và tính chất có lương, đáp ứng đầy đủ câu hỏi. |
| 5 | Mua sắm 55 triệu | Cần Giám đốc phòng ban phê duyệt. | 0 | 0 | True | Sai. Đơn hàng trên 50 triệu phải do Tổng Giám đốc (CEO) phê duyệt. |
| 12 | Thưởng Tết 6 tháng | Thưởng Tết tối thiểu 1 tháng lương. | 1 | 1 | True | Đúng mức tối thiểu 1 tháng lương cho nhân viên đủ 6 tháng. |
| 21 | Senior 9 năm phép & lương | 18 ngày phép. Lương Senior từ 20 đến 35 triệu. | 1 | 1 | True | Tính đúng 15 + 3 = 18 ngày phép và đúng khung lương Senior v2024. |
| 23 | Khóa học 25tr nghỉ 8 tháng | Hoàn trả 25 triệu vì chưa đủ 1 năm cam kết. | 1 | 1 | True | Đúng 100% số tiền hoàn trả (25 triệu) do vi phạm cam kết 1 năm. |
| 29 | Tạm ứng 8tr quá hạn 30 ngày | Trưởng phòng phê duyệt. Phạt 2% tháng trên 8 triệu. | 0 | 0 | True | Sai. Cần cả Kế toán trưởng duyệt và tính phạt quá hạn 15 ngày (80k). |
| 33 | Manager 12 năm phụ cấp & phép | Phép: 19 ngày. Phụ cấp: 1.500.000 VNĐ/tháng. | 1 | 1 | True | Đúng 15 + 4 = 19 ngày phép và đúng phụ cấp (ăn trưa + điện thoại). |
| 41 | Số ngày phép năm | Nhân viên được nghỉ 12 ngày phép năm. | 0 | 0 | True | Sai. Dùng chính sách cũ v2023 (12 ngày) thay vì bản hiện hành v2024 (15 ngày). |
| 46 | Thử việc có phép năm không | Thử việc không có phép năm, phải xin nghỉ không lương. | 1 | 1 | True | Nhận diện đúng phủ định chính sách: thử việc không có phép năm. |
| 50 | VPN cá nhân khi WFH | Được, miễn là đảm bảo kết nối an toàn. | 0 | 0 | True | Sai nghiêm trọng. Chính sách cấm VPN cá nhân, bắt buộc dùng WireGuard. |

Cohen’s κ: **1.0** (Đồng thuận tuyệt đối).

- Tỷ lệ đồng thuận quan sát được: $p_o = \frac{10}{10} = 1.0$.
- Tỷ lệ đồng thuận ngẫu nhiên kỳ vọng:
  $$p_e = P(\text{judge}=1) \times P(\text{human}=1) + P(\text{judge}=0) \times P(\text{human}=0) = (0.6 \times 0.6) + (0.4 \times 0.4) = 0.36 + 0.16 = 0.52$$
- Hệ số Cohen’s Kappa:
  $$\kappa = \frac{p_o - p_e}{1 - p_e} = \frac{1.0 - 0.52}{1 - 0.52} = \frac{0.48}{0.48} = 1.0$$
- Diễn giải: Mức độ đồng thuận hoàn hảo ($\kappa = 1.0 > 0.6$) chứng minh LLM Judge có khả năng phân biệt câu trả lời tốt/xấu cực kỳ đáng tin cậy. Judge bắt chính xác cả 4 ca sai lệch tinh vi (thẩm quyền phê duyệt, tính toán phạt, phiên bản lỗi thời và vi phạm bảo mật).

## Giới hạn và cách dùng judge

1. **Giới hạn cỡ mẫu:** Bộ calibration gồm 10 câu và bộ pairwise gồm 5 cặp câu hỏi. Mặc dù đạt $\kappa = 1.0$, mẫu thử nhỏ có thể chưa bao phủ hết các ca biên (edge cases) phức tạp hơn trong thực tế.
2. **Ảnh hưởng của Prompt và Temperature:** Cần duy trì `temperature = 0` và cấu trúc prompt chặt chẽ (định dạng JSON schema, yêu cầu dẫn chứng cụ thể) để duy trì tính ổn định.
3. **Quy trình triển khai khuyến nghị:**
   - Luôn sử dụng kỹ thuật hai lượt hoán đổi `swap-and-average` để triệt tiêu hiện tượng position bias.
   - Không xem quyết định của LLM Judge là chân lý tuyệt đối thay thế con người; cần có cơ chế human-in-the-loop đối với các ca `tie` hoặc các câu hỏi có mức độ rủi ro tuân thủ cao.
