# Spec: trạng thái snapshot ở reader

Ngày 18/10/2026. Đã triển khai và kiểm thử. [Plan](../plans/2026-10-18-report-snapshot-clarity.md), [nghiệm thu](../validation/2026-10-18-report-snapshot-clarity.md).

- Predicate current policy: schema >=2, evaluated không false, metrics tồn tại, quality policy của metadata/evaluation cùng v2, rubric v8. Release vẫn cần evidence policy và release_allowed; hiển thị ngày không cấp quyền gửi/lưu.
- Reader đặt ngày lập theo giờ Việt Nam và cảnh báo policy cũ trước summary. Timestamp thiếu/không hợp lệ hiển thị chưa xác định, không dùng thời gian hiện tại thay thế.
- Footer popup cho yêu cầu cập nhật khi report chưa theo policy hiện tại. Gọi hàng đợi `/api/briefing` op enqueue có sẵn, workspace ID từ button dataset; chặn bấm đôi, hiện lỗi và cho thử lại. Không tự gửi/lưu/phê duyệt hoặc đổi snapshot.
- Trạng thái trả về phải phân biệt queued/running/completed/failed, worker paused và model chưa cấu hình. Link theo dõi dùng workspace đã chọn; nếu enqueue trả job đang completed thì mở đúng report ID, không nói đang tạo mới.
- Detail versions chỉ chứng minh có phiên bản mới hơn, không chứng minh phiên bản đó đạt v8 hoặc release. Mở qua cùng reader với guard độc lập. Không tự thay report của approval.
- Đối chiếu nguồn vẫn giữ nguyên dữ kiện gốc, heading nói rõ thời điểm lập. Lịch hiện tại tiếp tục dùng freshness guard 15 phút; không sửa timestamp để làm tươi lịch.
- Không bump rubric hoặc thêm model call cho thay đổi trình bày này.
