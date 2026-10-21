# Spec: opportunity-aware brief

Rubric v7, schema report v2 giữ nguyên. `preparation_schema_version=3` thêm `answer_status=partial`, `remaining_gap`. provided/partial phải có value/quote thật từ nguồn sơ cấp và verdict riêng xác nhận answer/scope; partial không nâng pilot-ready. Không có value/quote/verdict thì unknown. Câu hỏi về mẫu không được xóa loại tài liệu đã biết. Partial gap được template hóa từ giá trị đã kiểm định, không để raw missing_information phủ nhận phần đã biết.

Nếu quote model không liên tục, chỉ được khôi phục từ toàn bộ value nguyên văn trong đúng nguồn đã trích (ít nhất 10 ký tự, không có invalid ref), giữ quote gốc để audit và vẫn cần semantic verdict cho answer/scope. Không có match nguyên văn thì không khôi phục. Numeric/unit mismatch trong giá trị có quote hợp lệ vẫn là lỗi cứng.

Scheduling window là cấu trúc có start_date/days/duration/timezone/label/basis, tính lịch Việt Nam. Mặc định phần còn lại của tuần này. Lời yêu cầu rõ từ người dùng ưu tiên email; yêu cầu tuần tới trong email được neo ngày nhận, chọn email mới nhất có meeting intent và bỏ quoted lines/forwarded block. Nếu phạm vi tuần yêu cầu đã qua, trả trạng thái cần xác nhận, không tự dời sang tuần khác. Hai tuần mâu thuẫn trong cùng yêu cầu phải thể hiện chưa rõ, không tự coi một tuần là đúng. Tuần này/tuần tới và this/next week được xử lý, chưa hứa parser mọi cách ghi ngày tự nhiên.

Tool calendar nhận start_date/days (tối đa 30)/duration (15–480), mặc định tương thích caller cũ. coverage giữ enum local_only/google_checked/unknown; scope/label là trường riêng. Report, chat và export dùng cùng scheduling_window. Với nhiều đối tác, không gắn chung một lịch sai phạm vi. Cache không reuse nếu start/end/duration/window khác dù slots rỗng giống nhau.

Nguồn profile được khám phá từ link thật cùng domain; nhận diện ve-chung-toi, contact và các trang ngôn ngữ có thật. Trích đoạn bounded giữ mốc thành lập, hồ sơ và vai trò/đầu mối nếu có. Thông tin website là self-description có observed_at, không chứng minh người gửi được ủy quyền. Chưa có mốc/đầu mối thì nói chưa xác minh, không tạo mục trống để đủ mẫu.

UI hiển thị readiness và vấn đề người đọc cần xử lý trước; kỹ thuật nằm trong details riêng. Không lộ pass_with_warning ở kết luận chính; approved actions vẫn dựa toàn bộ gate/rubric hiện tại. Thời gian backend giữ tổng hiện có, thêm phase chứ không ghi vào immutable report. Mẫu kiểm thử và kết quả thực tế phải ghi rõ scope, không gọi generation timing là end-to-end.
