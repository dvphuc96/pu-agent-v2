# Tự đánh giá sau sửa báo cáo Saigon Tech — 17/10/2026

Plan: `../plans/2026-10-17-opportunity-aware-brief.md`. Spec: `../specs/2026-10-17-opportunity-aware-brief.md`. Rubric v7; schema report v2, preparation v3. Không reset hoặc sửa dữ liệu báo cáo/phê duyệt cũ; không dùng computer use hoặc gửi email.

## Đọc như người dùng

Đạt để chuẩn bị trao đổi ban đầu. [Mẫu sau sửa](samples/2026-10-17-saigon-opportunity-replay.md) dùng email/lịch hoàn toàn giả lập và snapshot website công khai đã lưu, không phải dự án hoặc lịch thật của công ty.

- Yêu cầu “tuần tới” được chuyển thành phạm vi 19–25/10, có slot giả lập trong giờ làm việc ngày 19 và 20/10. Không kết luận hết giờ vì chỉ xem cuối tuần 17–18/10.
- Hóa đơn PDF/biểu mẫu scan là phần đã biết; bộ mẫu chưa chọn. Google Drive là nơi lưu đã nêu; hệ thống nhận OCR/tích hợp còn thiếu. Hai mục được giữ partial, không thành unknown hoặc hoàn toàn đầy đủ.
- Research có thêm quy mô tự công bố, mô hình offshore và hồ sơ/đầu mối trên trang tiếng Nhật. Trang tiếng Việt và tiếng Nhật có mốc thành lập khác nhau: giữ cảnh báo đối chiếu có nguồn, không tự coi một năm là lịch sử thống nhất hoặc xác minh hai hồ sơ cùng pháp nhân.
- Câu hỏi đi trực tiếp vào phân quyền, bộ trường OCR, tích hợp, bảo mật và người quyết định; có bước tiếp theo. Đề xuất mô hình hợp tác bổ trợ được nhận diện là giả thuyết.
- Metrics/gate thô và thời gian từng bước được giữ trong chi tiết; phần chính kết luận đủ cho cuộc gặp, còn điều kiện pilot phải xác minh.

Trong lượt model đầu, gate passed nhưng tự đọc thấy input_documents vẫn unknown: model dùng quote nối bằng dấu ba chấm. Không chấp nhận kết quả đó là xong. Đã sửa quote recovery có điều kiện nguyên văn, thêm regression và chạy model lại. Lượt sau giữ đúng partial. Khi đọc lại còn thấy lặp cảnh báo năm thành lập và số nguồn 2 trước 1 do alias URL; đã sửa view để không lặp cùng cảnh báo và sắp nguồn theo số citation mà không đổi số. Mẫu được render lại bằng cùng view hiện tại; giữ nguyên các factual prose từ lượt model thử.

## Kiểm chứng

- Hai lượt model thật: 39,059 và 40,420 giây cho riêng generation + evaluation. Lượt sau qua gate ngay lần đầu, không finding. Generator/judge dùng cùng model cấu hình; không phải đánh giá độc lập.
- Không gọi web tool hoặc gửi nội dung inbox thật trong replay; chỉ dùng public page snapshots, email giả lập và lịch giả lập.
- Python full deterministic: 714 passed, 11 skipped. File kiểm tra cú pháp JavaScript được chạy riêng bằng runtime Node: 13 passed, gồm 11 ca bị skip trong suite đầy đủ và hai ca đã qua. Tổng cộng 725 ca Python khác nhau đã thực thi thành công. Sau cùng siết profile-check chỉ xét trang hồ sơ (không lấy năm của công ty khác trong bài tin) và chạy lại toàn bộ regression opportunity-aware thành công.
- JavaScript runtime: 35 passed, gồm partial UI, phạm vi tuần yêu cầu, metrics được thu gọn, gate cũ không đủ chuẩn và timing không cộng lặp.
- Ruff trên các file Python sửa trong đợt này và `git diff --check`: pass.
- Dashboard khởi động lại với correction tắt; GET trang chính 200, JavaScript đã phục vụ rubric v7 và giao diện partial mới.
- Regression bao gồm anchor theo received date, user override, bỏ quote/forward và pilot timeline, tuần quá hạn/mâu thuẫn, nhiều đối tác khác tuần, một calendar read cho cùng phạm vi, cache đổi tuần, tác vụ nền, partial/quote/numeric và profile ở cuối trang dài.

## Giới hạn và hiệu năng

Chưa đo lại end-to-end inbox thực sau sửa; không dùng 40 giây trên để tuyên bố đã giảm tổng 98 giây. Có breakdown backend lock/session/agent và inbox scan/classification/calendar/research/approval để chẩn đoán lượt mới, tách khỏi collection/workflow. Không tăng web/model budget; calendar chỉ đọc sau triage và dùng chung theo phạm vi, phần công ty còn hạn vẫn tái dùng được khi đổi tuần.

Resolver xử lý tuần này/tuần tới và this/next week. Ngày cụ thể/ngày mai chưa phân giải được sẽ giữ unknown kèm lý do thay vì tự đề xuất sai tuần. Nguồn website không phải xác minh độc lập về năng lực, pháp nhân hoặc quyền đại diện; pilot vẫn cần xác nhận đầu vào và phê duyệt.
