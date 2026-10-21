# Spec: briefing đối tác có ích cho cuộc họp

Trạng thái: đã triển khai và kiểm thử offline ngày 16/10/2026, từ kế hoạch `../plans/2026-10-16-partner-brief-relevance.md`. Còn đánh giá chất lượng/latency trên model thật.

## Hợp đồng nội dung

Giữ schema report v2 và các section chuẩn. Summary giới thiệu công ty; public_research chứa điểm nổi bật công khai; email_need chứa lời người gửi; meeting_preparation chứa câu hỏi và giả thuyết đề xuất; không lặp lịch trong prose. Không thêm prose ngoài vùng được evaluator kiểm tra. Chat dựng briefing từ các phần này, không dùng meeting_context làm highlight công ty. Có fallback đọc report cũ.

Chat dùng cùng citation presentation với reader/export. Nguồn được xếp theo mức trích dẫn và chủ đề, loại URL trùng chuẩn hóa. Danh sách mặc định tối đa tám nguồn nhưng phải giữ mọi nguồn đang được trích trong chat. Thiếu nguồn thì hiển thị số thực, không bịa đủ năm. Loại citation nội bộ trong chat phải dọn whitespace, dấu câu. Cảnh báo quyền đại diện hiển thị một lần; mâu thuẫn hiển thị mô tả cụ thể có nguồn. Không tuyên bố report đã đạt chỉ vì có nội dung.

## Research

Query chính thức dùng site:domain và tên công ty riêng; query tin công khai dùng tên công ty, không quote domain+tên. Chỉ đưa các chủ đề công khai allowlist vào search. Ưu tiên investor/annual report/quy mô/vận hành/công nghệ. Link sản phẩm chi tiết mặc định tối đa một nếu không có yêu cầu sản phẩm cụ thể. Giữ ngân sách đọc tối thiểu cho search chủ đề còn thiếu trước khi duyệt link phụ. Không tăng tổng số query/read/thời gian hiện hành. Lưu coverage và số lần đọc để chẩn đoán.

PDF đi qua cùng kiểm tra public DNS, port và redirect; tối đa 2 MB, 60 trang, nội dung 100k ký tự, từ chối mã hóa hoặc file quá giới hạn; thực thi parser trong subprocess có timeout 8 giây. Không có parser hoặc không đọc được phải báo thiếu dữ kiện, không coi là bằng chứng đã đọc. Không tải nguồn qua browser.

## Lịch

Luồng structured availability dùng timezone Asia/Ho_Chi_Minh, buổi sáng 09:00–12:00 và chiều 13:30–17:30, thứ Hai đến thứ Sáu; lead time mặc định 60 phút. Có cấu hình giờ/break/lead qua policy truyền vào hàm đọc lịch. Sinh ứng viên không chồng, tối đa ba gợi ý, ưu tiên khác buổi/ngày, chỉ phần còn lại của tuần. Lưu phạm vi local_only/google_checked/unknown riêng với trạng thái có slot; không biến local_only thành đã xác nhận toàn bộ lịch. Nhánh legacy giữ định dạng cũ nhưng dùng cùng cửa sổ giờ làm việc; timestamp không có end không được dùng làm lịch xác nhận.

## Kiểm định và hành động

Giữ mandatory semantic review và mọi hard gate số liệu/nguồn/danh tính. Thêm issue code/mức độ/message/affected_actions từ kết quả thực, hiển thị nguyên nhân cụ thể. Không đổi quyền approval/gửi bằng cách chỉ đổi message. Đọc/tải draft vẫn được; chưa thêm nút lưu nháp ở đợt này vì cần đường lưu riêng không nhập vào tri thức đã xác minh. Nhãn không nói được lưu như hoàn tất khi gate thất bại.

Judge kiểm tra lặp, trọng tâm, khoảng trống và phân biệt tự khai/đề xuất. Một vòng repair chung với structural repair hiện có; không tự mở vòng LLM hoặc web vô hạn. Bổ sung bằng chứng theo topic còn thiếu trong ngân sách collector, không thêm pass thu thập sau khi tổng budget đã hết. Cache rubric tăng phiên bản để report cũ phải đánh giá lại.

## Nghiệm thu

Fixture trang chủ nhiều sản phẩm có báo cáo/công nghệ phải lấy được nguồn doanh nghiệp ưu tiên; query không chứa cụm domain+tên quote hoặc nội dung email riêng tư. Chat không lặp email/lịch/cảnh báo và không mất nguồn trích sau vị trí tám. Fixture lịch lúc 11:08 thứ Sáu 16/10/2026 phải đưa giờ chiều không qua nghỉ trưa, cuối tuần không có slot. Mâu thuẫn và gate failure có lý do cụ thể; không nới bảo vệ để đạt test. Kiểm tra PDF giới hạn và lỗi parser bằng dữ liệu local giả lập. Kiểm thử Python/JS và lint; chất lượng/latency model thật được báo riêng, không suy ra từ fake model.

## Kết quả triển khai

- Query/domain, xếp hạng và giới hạn sản phẩm, ngân sách cho topic chưa có nguồn, PDF subprocess, chat/citation, issue disclosure, lịch và rubric v4 đã cập nhật.
- Đã đọc evaluation local của bản Vinamilk được phản ánh: semantic review passed nhưng contact coverage bị gắn conflicting do khác miền email với kênh công khai. Generation/repair được hướng dẫn phân biệt đúng; không sửa trực tiếp report đã lưu hoặc bỏ gate. Test repair chứng minh cần tạo bản mới và judge lại; mâu thuẫn tồn tại sau repair vẫn bị chặn.
- Python: 676 passed, 11 skipped; JavaScript: 29 passed; Ruff đạt. Bộ Python tập trung chạy lại sau các chỉnh sửa chat: 56 passed. Toàn bộ kiểm tra dùng dữ liệu giả lập/temp database; truy vấn production chỉ đọc evaluation, không chuyển inbox cho model.
- Lưu nháp riêng, OCR PDF scan và giao diện cấu hình giờ làm việc không thuộc đợt này. Policy giờ làm việc đã cấu hình được qua API hàm Python; chưa có form UI. Không có thêm vòng thu thập sau judge: bổ sung bằng chứng diễn ra trong tổng budget collector, repair generation vẫn tối đa một.
