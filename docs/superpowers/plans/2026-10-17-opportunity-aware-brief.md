# Plan: lịch và báo cáo bám sát cơ hội hợp tác

Đã được anh cho phép lập plan và sửa tiếp. Không reset database, sửa báo cáo/phê duyệt cũ hoặc dùng computer use.

Đã triển khai; [kết quả tự kiểm thử](../validation/2026-10-17-opportunity-aware-brief.md).

1. Lịch: giải quyết tuần yêu cầu từ lời người dùng hoặc email mới nhất có lời đề nghị họp. Tuần tới tính theo ngày nhận email tại Việt Nam, không theo ngày mở lại báo cáo. Đọc lịch sau triage, dùng chung snapshot khi cùng phạm vi; mỗi đối tác có phạm vi riêng, không ép tất cả về tuần này. Cache phải so cả phạm vi và duration. Không suy ra lịch đối tác từ lịch của mình.
2. Checklist: thêm partial và remaining_gap có quote/value/scope, qua cùng kiểm định deterministic và semantic. Đã biết loại tài liệu không có nghĩa đã nhận mẫu. Chỉ provided mới đủ cho đầu vào pilot; partial phải giữ phần đã biết và câu hỏi còn thiếu nhất quán trong reader/export.
3. Research: ưu tiên trang giới thiệu, hồ sơ công ty/đầu mối và nguồn đa ngôn ngữ có thật trên cùng miền; trích đoạn giữ các mốc hồ sơ khi có. Không tăng budget hoặc bịa legal identity/nhân sự hiện tại. Prompt khai thác profile và khoảng trống phù hợp với năng lực đối tác thay vì lặp danh sách tech stack/email.
4. Trình bày: năm câu hỏi tự nhiên, không lặp “Gợi ý”. Trạng thái đọc chính nói đủ cho trao đổi ban đầu/còn cần làm rõ. Gate kỹ thuật, metrics và performance chỉ ở chi tiết kỹ thuật. Không thay đổi điều kiện phê duyệt.
5. Timing: ghi các khoảng thời gian backend riêng cho chờ lock, chuẩn bị phiên và agent; ghi scan/classification/calendar/partner research/approval trong luồng inbox. Giữ scope tách biệt; không cộng số workflow vào total hoặc gọi phần chênh lệch là lỗi nếu chưa đo.
6. Nghiệm thu: offline regression nhiều đối tác/khác tuần, received-date anchor, quoted mail, lỗi Calendar, partial và numeric hard gate, cache phạm vi, diagnostics và timing; chạy model với public snapshot Saigon Tech + email giả lập, tự đọc rồi sửa tiếp nếu chưa hữu ích. Không gửi inbox thật cho model để debug.

Spec: `../specs/2026-10-17-opportunity-aware-brief.md`.
