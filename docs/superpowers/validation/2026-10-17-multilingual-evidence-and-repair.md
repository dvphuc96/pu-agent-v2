# Nghiệm thu: đối chiếu số đa ngôn ngữ và repair

Ngày 17/10/2026. Đã triển khai rubric `report-quality-rubric-v8`, numeric contract `numeric-evidence-v2`; report schema v2 và preparation v3 giữ nguyên.

## Kết quả

- Đánh giá lại chỉ đọc report gốc `report-b6cb4752-de2f-4f8a-aa86-d6c243b5ac23`: C4 chứa 2014/2018/2019 không còn thiếu số 2018 trong nguồn `設立 2018年12月`. Numeric supported; không còn missing number/date/unit. Blocker scale conflicting của snapshot gốc vẫn tồn tại, nên report gốc vẫn không phát hành. Không sửa snapshot hoặc phê duyệt cũ.
- Đối chứng tiếp tục chặn sai năm/tháng/ngày/đơn vị, nguồn không hợp lệ, snippet trộn cùng nguồn sơ cấp và claim bị judge phủ định. Chỉ ít finding hơn nhưng còn cùng blocker bị từ chối. Đổi claim ID không che được blocker cũ.
- Orchestrator không sinh lại report cho ký hiệu ngoài khả năng evaluator hoặc judge không khả dụng. Ngân sách tối đa một generation repair vẫn dùng chung với structural repair. Giữ candidate draft chỉ khi có cải thiện blocker thực và không mất dữ kiện thiết yếu/lịch.
- Reading view giữ cảnh báo mốc hồ sơ một lần khi đối chiếu đủ cùng các năm và citation; raw sections vẫn được giữ để audit.

## Kiểm thử

- Toàn suite Python: **733 passed, 11 skipped** trong 20,32 giây. Chạy riêng bộ syntax với Node đã cấu hình: **13 passed**, gồm 11 ca skip và 2 ca đã tính trong suite. Tổng **744 ca Python khác nhau** đã chạy thành công.
- Hai bộ CJS runtime: **35 passed**.
- Ruff trên Python thay đổi trong đợt này và `git diff --check`: đạt.
- Regression/integration gồm CJK/full-width/raw offset, precision, invalid date, identifier, duration, decimal/unit, niên hiệu không hỗ trợ, snippet, semantic rejection, blocker selection, dữ kiện partial và call count orchestration.

## Replay model và tự đọc

Hai lượt dùng snapshot web công khai của ca gốc, email và lịch hoàn toàn giả lập. Không gửi email riêng tư tới model, không ghi report vào database ứng dụng, không gửi email ra ngoài.

| Lượt | Thời gian viết + kiểm định | Call | Gate | Repair |
| --- | --- | --- | --- | --- |
| 1 | 40,137 giây | 1 generation + 1 judge | Đạt | Không cần |
| 2 | 50,166 giây | 1 generation + 1 judge | Đạt | Không cần |

Đã đọc toàn bộ lượt 2 và xuất [bản mẫu](samples/2026-10-17-multilingual-evidence-replay.md). Mẫu giữ rõ thông tin công ty, nhu cầu email, đề xuất pilot, câu hỏi, phần tài liệu đã biết/còn thiếu, lịch tuần 19–25/10 và năm nguồn công khai thực sự được trích. Các mốc 2014/2018/2019 được quy về nguồn tương ứng, không tự chọn một năm hoặc khẳng định cùng pháp nhân.

Ở vai trò người dùng, mẫu đủ để chuẩn bị buổi trao đổi khám phá nhu cầu; không phải xác nhận pháp lý hoặc bằng chứng pilot đã sẵn sàng. Tóm tắt còn nhắc lại một phần số liệu trong hồ sơ, nên chưa coi biên tập đã hoàn hảo. Lỗi chặn nhầm ký hiệu năm và vòng repair không tiến triển đã được xử lý trong phạm vi đã kiểm chứng.

## Giới hạn

Đây là replay từ snapshot công khai, không phải một lượt inbox thật mới. Hai timing chỉ gồm viết/kiểm định, không gồm scan/classification/thu thập/lưu/xuất; không dùng để kết luận thời gian backend 153,872 giây đã giảm hoặc đưa SLA/p95. Generator và judge dùng cấu hình model hiện có, không phải đánh giá độc lập.

Chưa hỗ trợ quy đổi niên hiệu Nhật, chữ số Hán hoặc mọi đơn vị CJK; giới hạn nhận diện được giữ draft với đúng nguyên nhân. Kiểm tra số không thay xác minh quan hệ, chủ thể, ngưỡng hay pháp nhân. Không reset dữ liệu, thay nội dung report cũ hoặc tự duyệt/gửi. Cần tạo report mới để sử dụng rubric v8.
