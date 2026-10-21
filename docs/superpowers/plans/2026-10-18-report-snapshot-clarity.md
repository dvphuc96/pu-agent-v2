# Plan: phân biệt báo cáo cũ với kết quả hiện tại

Trạng thái: đã triển khai và kiểm thử ngày 18/10/2026.

## Bằng chứng và nhận xét

File anh gửi khớp report `report-b6cb4752-de2f-4f8a-aa86-d6c243b5ac23`, tạo 14:21 ngày 17/10/2026, rubric v7, workflow 97,77 giây. Database chưa có report v8. Dashboard đang phục vụ JavaScript v8; không có bằng chứng một report mới chạy v8 vẫn lỗi C4. Không sửa lại parser hoặc hạ gate từ kết quả cũ.

Nội dung hữu ích cho khám phá nhu cầu: có loại tài liệu, Drive, phòng ban, số người dùng, câu hỏi và giả thuyết pilot. Điểm chưa tốt: lặp giữa summary/context, cảnh báo giới hạn nghiên cứu gây hiểu nhầm, kết luận kiểm định cũ không nổi bật như dữ liệu lịch cũ. Các thay đổi generation/reading view v8 đã xử lý hai vấn đề nội dung đầu trong phạm vi kiểm thử trước; chưa khẳng định report thật mới đã đạt.

## Triển khai

1. Hiện ngày lập và cảnh báo bản cũ ngay đầu reader, không giấu trong chi tiết kiểm định. Dùng cùng predicate policy cho nhãn và release controls.
2. Trong popup có đường tạo phiên bản mới bằng hàng đợi nghiên cứu hiện có, giữ nguyên bản đang đọc. Nếu worker tạm dừng/chưa nối model phải nói đúng trạng thái, không báo đang chạy giả.
3. Khi đã có bản mới hơn, cho mở rõ phiên bản đó; không tự thay report của attachment/phê duyệt.
4. Ghi rõ phần đối chiếu factual/calendar là snapshot tại thời điểm lập báo cáo, không phải kiểm tra lịch hiện tại.
5. Kiểm thử reader với v7/v8, timestamp, escape, bản mới hơn, queue success/error/paused. Kiểm tra cache/delivery vẫn từ chối rubric cũ; không reset hoặc gửi email/inbox tới model để debug.

## Nghiệm thu

Không đổi report/hash/approval đã lưu; không tự mở gate. Báo cáo cũ không mang nhãn đạt chuẩn hiện tại. Người đọc nhìn thấy ngày và cách cập nhật trước nội dung chính. Kết quả: [validation](../validation/2026-10-18-report-snapshot-clarity.md).
