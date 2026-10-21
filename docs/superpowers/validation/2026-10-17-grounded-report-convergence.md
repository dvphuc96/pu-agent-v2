# Tự kiểm thử và đánh giá báo cáo — 17/10/2026

Plan/spec: `../plans/2026-10-17-grounded-report-convergence.md`, `../specs/2026-10-17-grounded-report-convergence.md`. Rubric mới `report-quality-rubric-v6`; schema báo cáo vẫn v2. Báo cáo và phê duyệt cũ không được sửa hoặc tự nâng chuẩn.

## Kết quả đọc như người chuẩn bị cuộc gặp

Đạt để chuẩn bị buổi khám phá nhu cầu. Người đọc có bối cảnh công ty, vận hành liên quan, nhu cầu email riêng, năm câu hỏi và giả thuyết pilot có tiêu chí đánh giá. Các giả thuyết được ghi là đề xuất. Chưa đủ để phê duyệt triển khai pilot: quyền đại diện và các điều kiện chưa có bằng chứng vẫn được nêu rõ. Có thể đọc [mẫu sau tự sửa](samples/2026-10-17-vinamilk-replay.md); email và lịch trong mẫu hoàn toàn giả lập, phần công ty dùng snapshot nguồn công khai đã lưu.

| Tình huống model thật | Kết quả đọc và đối chiếu | Thời gian |
| --- | --- | --- |
| Email giả lập chỉ đề nghị trao đổi, chưa có phạm vi chi tiết | Qua gate lần đầu; bảo mật/ngân sách/thời hạn không bị coi đã cung cấp; vai trò chỉ tự khai. Bỏ PDF snippet khỏi factual evidence. | 44,780 giây |
| Email giả lập có phòng Kế toán, 20 người dùng, hóa đơn PDF, SharePoint, ngân sách 200 triệu và người phê duyệt | Qua gate lần đầu; sáu giá trị pilot giữ self_reported, không tạo gap phủ nhận chúng. Bảo mật và hạn hoàn thành vẫn chưa rõ. | 38,512 giây |
| Cố ý chèn câu có 65 quốc gia kèm năm 2023 thiếu nguồn, và 200.000 điểm bán chỉ có snippet | Gate chặn dù judge cho kết quả ngữ nghĩa tốt. Một lần sinh sửa loại cả hai lỗi, giữ số 65 với phạm vi nguồn không nêu kỳ; bản sửa qua gate, không còn finding. | 44,633 giây |

Các thời gian trên chỉ gồm viết/kiểm định (ca thứ ba gồm judge của bản lỗi, viết sửa và judge lại), không gồm đọc inbox, thu thập web, mạng hoặc render giao diện. Không dùng chúng làm benchmark end-to-end, p95 hoặc SLA. Generator/judge cùng model cấu hình, chưa phải đánh giá độc lập. Không gọi web tool để cập nhật snapshot trong lượt replay; không gửi email/inbox thật lên model.

Đọc cả ba bản đầu ra cho thấy phần research có trọng tâm hơn danh mục sản phẩm; không còn escape newline, không bịa năm cho con số và không nhầm yêu cầu trao đổi thành dữ liệu đã chốt. Trong quá trình tự đọc phát hiện bản xuất bị thiếu mục lịch khi không có slot; đã sửa Markdown/HTML/print/DOCX để ghi rõ kết quả trống tại thời điểm kiểm tra, phạm vi local và chưa kiểm tra Google/lịch đối tác. Chỉ liệt kê nguồn thực sự dùng, không chèn link để đủ 5–8 nguồn. Phụ lục đối chiếu giữ riêng; reader thu gọn.

## Kiểm tra kỹ thuật

- Bộ Python deterministic đầy đủ cuối cùng: 700 passed, 11 skipped do Node không nằm trong PATH mặc định. 12 ca convergence đều qua, gồm alias anchor khi lọc nguồn. Sau đó chạy toàn bộ file kiểm tra cú pháp JavaScript với runtime Node đã cài: 13 passed (gồm 11 ca bị skip trước đó và hai ca đã qua trong suite). Tổng cộng 711 ca Python khác nhau đã được thực thi thành công qua hai lượt.
- JavaScript runtime: 33 passed, bao gồm citation bị khuyết số, lọc nguồn chưa dùng, gate cuối khác semantic verdict, reader rộng và trạng thái checklist.
- Ruff trên toàn bộ file Python thay đổi trong đợt này: pass.
- Regression từ lỗi thực: không dùng snippet/derived trong generation hoặc routing; dedup email và lịch; numeric/date hard gate; quote/value/scope; requested khác provided; không có verdict thì unknown; repair không cải thiện giữ draft, không lặp vô hạn hoặc tạo approval; view/export không thay snapshot; empty-calendar và alias anchor khi lọc nguồn.
- Dashboard khởi động lại với correction tắt, GET trang chính 200 và JavaScript phục vụ rubric v6. Không dùng computer use, không thao tác inbox hoặc gửi email.

Giới hạn còn lại: nguồn chưa tải/parse được không tạo dữ kiện; bài mới/financial metrics chỉ được đưa vào khi có bằng chứng phù hợp. Chất lượng trên inbox thực cần theo dõi qua sử dụng; ba replay không chứng minh mọi công ty hoặc mọi lần sinh đều đúng. Bản không đủ bằng chứng vẫn giữ nháp và chặn phát hành.
