# Plan và contract: email gần nhất dùng chung luồng briefing

Ngày 18/10/2026. Đã triển khai và kiểm thử.

## Nguyên nhân

`is_inbox_request` bỏ sót câu “Kiểm tra 10 email gần nhất giúp anh, xem có gì cần chú ý không?”. Luồng graph tổng quát tự gọi tool đọc Gmail/nghiên cứu rồi model diễn giải kết quả, không tạo reply/thẻ báo cáo theo contract inbox briefing.

Report `report-93a1063c-764f-4f13-91e6-982e9a724388` có rubric v8 nhưng không có metadata workspace/inbox/availability của luồng inbox chuyên biệt. Evaluation thực ghi thiếu request/contact, claim C6 bị semantic rejection, lịch stale và độ phủ thấp. Không có cơ sở nói chỉ thiếu ngân sách/người quyết định nên quality gate không đạt. Con số tổng hợp không phải xác suất chính xác của report.

## Các bước và contract đã thực hiện

1. Nhận câu tiếng Việt/Anh có email gần nhất/latest/recent và số N. Mặc định 10, giới hạn 100; ghi giới hạn thật trong reply. Giữ luồng ngày khi có “hôm nay/today”, không chuyển yêu cầu gửi/xóa/hướng dẫn hoặc phủ định sang scan.
2. Tool `scan_inbox_recent` sync N email INBOX không dùng cửa sổ một ngày. Trả ID lô sync và chỉ đọc các ID đó khi fresh; không trộn email local đã archive/thuộc lô cũ. Gmail rỗng thì trả rỗng, không phục hồi dữ liệu local cũ. Sync lỗi trả snapshot local có fresh=false/warning rõ ràng.
3. Liệt kê đúng lô đã chọn theo thời gian, hiển thị giờ Việt Nam. Tiêu đề/người gửi là text không được phá bảng hoặc tạo link điều khiển. Các dấu hiệu bảo mật, thanh toán quá hạn, thay đổi lịch chỉ được gọi là dấu hiệu từ tiêu đề, không phải xác nhận sự cố.
4. Phân loại hợp tác, nguồn công ty, báo cáo, lịch 45 phút, gate và approval dùng lại `InboxChatBriefing`; không có vòng LLM tổng hợp reply sau report để bịa ý nghĩa điểm số hoặc lịch. Trả report references thực cho thẻ đọc/copy/duyệt trong chat. Không in đường dẫn filesystem làm điểm giao báo cáo.
5. Không đổi ngưỡng gate hoặc tự coi report hiện tại đã đạt; không sửa nội dung report đã lưu.

## Kiểm chứng

- **67 passed**: bộ latest inbox mới, inbox chat và Gmail. Integration chạy qua `app.respond` đúng câu anh hỏi, có đối tác nhận từ ngày cũ, bảng 10 email và report reference v8. Toàn bộ Gmail/model/collection trong kiểm thử được giả lập.
- Toàn bộ Python deterministic: **748 passed, 11 skipped** trong 23,25 giây. Các ca skip là syntax check cần Node, không do lỗi test.
- Ruff các file Python thay đổi và `git diff --check`: đạt.
- Không chạy inbox/model thật để debug hoặc tạo report thay anh; chỉ đọc metadata/evaluation của report đã lưu để xác định nguyên nhân. Không reset database, gửi email hoặc thay phê duyệt.

Thay đổi này xác nhận câu hỏi đi đúng luồng và đầu vào đầy đủ hơn; không chứng minh report nghiên cứu thực tế kế tiếp sẽ luôn qua gate.
