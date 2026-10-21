# Chat: nút Dừng và thời gian trực tiếp

Ngày 18/10/2026. Đã triển khai cho chat chính và dock bên cạnh.

- Khi gửi, nút mũi tên đổi thành hình vuông với nhãn Dừng trả lời. Khi yêu cầu dừng đã gửi, hiện Đang dừng và khóa bấm lặp. Khi kết thúc/lỗi trở lại nút Gửi; nội dung đang gõ cho lượt tiếp theo được giữ.
- Mỗi lượt có đồng hồ mm:ss (hoặc h:mm:ss), chạy cả trước và trong lúc stream. Tick chỉ cập nhật text của đồng hồ, không render lại Markdown hoặc thay scroll. Khi done/cancel/error, đồng hồ dừng và hiển thị thời gian đã chạy; đây là thời gian người dùng chờ trên trình duyệt, không thay metric backend.
- Request ID riêng cho mỗi lượt, SSE xác nhận đăng ký trước khi chạy. Bấm dừng trước xác nhận sẽ được gửi sau khi đăng ký, tránh race mất yêu cầu dừng. Endpoint stop không cần khóa agent, không ảnh hưởng lượt khác và xóa đăng ký sau kết thúc.
- Backend hủy hợp tác tại checkpoint sự kiện và trước khi lấy khóa/chạy agent. Một lời gọi model/công cụ đồng bộ đang chờ phải trả về trước khi dừng được; UI nói rõ đang chờ bước đó. Không giả vờ đã hủy upstream hoặc thu hồi tác động đã hoàn tất.
- RunCancelled là control flow, không bị generic Exception handler coi là lỗi provider để retry. Workflow research bị hủy ghi lý do Cancelled by user, không để trạng thái running. Lượt chat bị ngắt trước khi lưu được ghi trong lịch sử là đã dừng; không thêm exchange trùng nếu app đã lưu trước đó. Phần text nhận trước dừng được giữ trên giao diện, không coi là câu trả lời hoàn chỉnh.

## Kiểm thử

- Toàn suite Python trước regression cuối: 752 passed, 11 skipped; sau khi thêm regression hủy ngay tại workflow_started, chạy lại nhóm cancellation/inbox/repair: 54 passed. Tổng 753 ca Python khác nhau đã chạy thành công trong đợt này.
- JavaScript runtime reader/notebook/live controls: 42 passed. Ca mới kiểm tra mũi tên → vuông → gửi, timer tiếp tục khi đã có token, early-stop chỉ gửi một lần, partial/draft giữ nguyên và cleanup khi lỗi mạng. Sau chỉnh thông báo retry, chạy lại ba ca live controls: đạt.
- Ruff trên Python thay đổi và git diff --check: đạt. Không dùng computer use hoặc model/inbox thật để test.
- Dashboard khởi động lại giữ dữ liệu; smoke endpoint dùng ID không tồn tại, không dừng lượt thật hoặc tạo job.
