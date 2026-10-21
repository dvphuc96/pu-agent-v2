# Nghiệm thu: trạng thái phiên bản báo cáo

Ngày 18/10/2026. [Plan](../plans/2026-10-18-report-snapshot-clarity.md), [spec](../specs/2026-10-18-report-snapshot-clarity.md).

## Nhận xét báo cáo anh gửi

Bản này chưa đủ tốt để coi là báo cáo hoàn tất. Phần nhu cầu, dữ liệu đã biết và câu hỏi khám phá có ích; không nên gọi cả báo cáo là vô dụng chỉ vì chưa chốt ngân sách, thời hạn hoặc quyền đại diện. Các phần chưa biết này cần thể hiện đúng phạm vi cuộc gặp đầu tiên.

Điểm cần cải thiện:

- Summary lặp khá nhiều giới thiệu công ty trong context. Thông tin quy mô cần ghi rõ tự công bố và khác thời điểm/phạm vi; không tự kết luận mâu thuẫn từ các ngưỡng `50+` và `>150`.
- Sáu nguồn công khai cùng một publisher không tương đương sáu nguồn xác nhận độc lập. Chưa có tin có ngày phù hợp thì nói chưa tìm được, không tuyên bố dữ liệu đã mới.
- Câu “không thực hiện nghiên cứu bổ sung” dễ khiến người đọc hiểu agent chưa research; cần mô tả chính xác nguồn nào được dùng và khoảng trống nào còn lại. Prompt v8 đã được chỉnh trong đợt trước, không sửa câu factual trong snapshot cũ bằng regex.
- Kết quả C4, scale và lịch cũ cần được đọc theo thời điểm lập. Lịch stale bị ẩn là đúng; phần audit vẫn chứa phát biểu lịch từ snapshot gốc nên heading phải nêu rõ thời điểm.

## Xác định nguyên nhân

File có cùng nội dung, timing và lịch với `report-b6cb4752-de2f-4f8a-aa86-d6c243b5ac23`, tạo `2026-10-17T07:21:41.139+00:00` (14:21 giờ Việt Nam), rubric v7. Workflow 97,768 giây, backend chat 153,87 giây, lịch kiểm tra 14:19. Database kiểm tra chỉ đọc hiện có ba report, đều v7; chưa có report v8 mới.

Đối chiếu numeric của đúng claim C4 với các excerpt web được trích bằng `numeric-evidence-v2`: supported=true, missing number/date/unit đều rỗng. Không chạy model hoặc ghi đè kết quả kiểm định cũ. Điều này chỉ xác nhận lỗi parser cũ không còn tái hiện với C4, không chứng minh scale conflict đã được xử lý hoặc toàn bộ report được phát hành.

## Đã sửa

- Đặt ngày lập theo giờ Việt Nam và cảnh báo chưa được đánh giá theo chuẩn hiện tại trước summary, dùng chung predicate với nhãn chất lượng. Timestamp thiếu/sai không biến thành thời gian hiện tại.
- Reader chat và notebook cùng cảnh báo bản cũ. Notebook không mang badge đạt chỉ vì snapshot cũ có release_allowed=true.
- Popup cho tạo bản cập nhật qua hàng đợi có sẵn; phân biệt đã xếp hàng, worker chờ, tự động tạm dừng, thiếu model, lỗi và hoàn tất. Chặn bấm đôi, lỗi hiển thị text và cho thử lại. Đường đọc bản hoàn tất trỏ đúng report ID.
- Có phiên bản mới hơn thì cung cấp nút mở riêng; không tự thay nội dung attachment đang đọc hoặc report được phê duyệt. Bản mới hơn vẫn được kiểm tra policy riêng.
- Heading audit ghi rõ “tại thời điểm lập báo cáo”. Không sửa factual prose, nguồn, hash, lịch hoặc approval snapshot.

## Kiểm chứng

- Hai bộ CJS runtime: **39 passed**, gồm test đọc đúng phiên bản, cảnh báo trước prose, ngày giờ, không mutate snapshot, queue bấm đôi/trạng thái/error và escape.
- Python số liệu đa ngôn ngữ, cache, availability safety, repair integration: **38 passed** trong 5,74 giây.
- Node syntax check hai file JS thay đổi và `git diff --check`: đạt.
- HTTP GET chỉ đọc xác nhận dashboard đang trả JavaScript có cảnh báo snapshot, nút cập nhật và rubric v8.

Không chạy một lượt inbox thật mới, không gửi email hoặc dữ liệu riêng tư tới model, không tạo job thật để test nút và không reset database. Queue được kiểm thử bằng HTTP mock trong runtime JS; backend queue hiện có không thay đổi. Nội dung v8 từng được thử bằng model ở [nghiệm thu trước](2026-10-17-multilingual-evidence-and-repair.md); không dùng lần đó để khẳng định có report inbox mới trong database.
