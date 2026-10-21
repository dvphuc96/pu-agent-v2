# Spec: grounded report convergence

Được phép triển khai và tự kiểm thử/sửa tiếp. Kế hoạch: `../plans/2026-10-17-grounded-report-convergence.md`.

## Text và evidence

Text normalization chỉ áp dụng các trường prose của output model, trước evaluate/freeze/hash. Đổi literal \\n/\\r\\n/\\t khi rõ là bố cục văn bản, giữ URL/path/code literal; không unicode_escape hoặc decode nguyên JSON. Model source IDs, số, ngày, URL không được thay đổi. Có regression Vietnamese, double escaping và URL chứa escape.

EvidenceBundle generation payload bỏ derived và snippet_only. Dedupe theo canonical URL hoặc nội dung chuẩn hóa cùng source_type. Nguồn gốc không bị xóa khỏi workspace; lead không được gọi là nguồn đã đọc. Chỉ số unread/full và lỗi đọc có mã an toàn để chẩn đoán; không đưa raw exception có thông tin nhạy cảm vào UI.

## Checklist

Mỗi item: key, answer_status (provided/requested/unknown), value, scope (identity/pilot/company_context/meeting/unknown), state (known/self_reported/unknown/conflicting), summary, source_ids, evidence_quote. Value cụ thể và quote phải đối chiếu được; thiếu thì unknown, không mặc định provided. Provenance không thay thế answer status. Quotation phải tồn tại trong nguồn sơ cấp đã đọc; sai số hoặc ref là lỗi cứng.

Thông tin mới do email cung cấp vẫn self_reported. Muốn thảo luận bảo mật/chi phí không cung cấp cấu hình bảo mật/ngân sách; vai trò nhóm quan tâm không chốt nhóm pilot. Thời lượng/cuộc hẹn thuộc meeting, không được làm timeline pilot. ERP công khai thuộc company_context nếu chưa xác nhận là hệ thống của pilot. Verdict checklist từ judge hiện tại phải chỉ rõ quote thực sự chứa câu trả lời và đúng scope; thiếu verdict thì không nâng positive state.

Checklist và các gap dẫn xuất dùng cùng assessment. Chỉ thêm các gap mặc định theo item còn thiếu; prose gaps khác được giữ như research limits. Không cho raw missing_information phủ nhận một giá trị đã được đối chiếu. View cuối đóng băng trước lưu/hash; mọi prose factual được judge đối chiếu. Các nhãn trạng thái/gap dẫn xuất từ kết quả kiểm định, không thêm factual prose sau judge.

## Repair

Feedback gồm từng claim/field lỗi: id/key, text/summary, source IDs, reason, đoạn nguồn thích hợp và missing numbers/date/units. Snippet không được dùng để vá. Câu có số đúng và năm so sánh thiếu nguồn phải tách/bỏ mệnh đề thiếu, không kết luận số chính sai.

Tối đa một generation repair chung ngân sách structural repair. Chỉ thay candidate nếu pass hoặc giảm lỗi theo thứ tự: identity/ref/numeric/unsupported, rồi field/editorial. Ghi before/after và no-improvement; không giả báo “đã sửa xong”. Nếu chỉ thiếu source và không còn ngân sách, đề nghị loại nhận định không thiết yếu hoặc trả nháp có ích; không tăng web budget vô hạn. Giữ draft tốt hơn khi provider/candidate lỗi.

## Presentation và version

Rubric/version context thay đổi để cache cũ không được tự coi đạt. Trạng thái chính kết luận theo gate cuối, ví dụ “Chưa phát hành: còn 2 nhận định chưa đối chiếu được”; semantic passed chỉ là một bước trong chi tiết. Gộp trùng finding và dịch message người dùng; giữ code/diagnostics gốc ở phần kỹ thuật.

Với report mới, nguồn chính là nguồn được trích và thực sự đã đọc, title và citation number rõ. Không tự đánh lại số khi lọc. Nguồn lead/không dùng và audit nội bộ để riêng; không ghi “đã trích” cho nguồn không được dùng. Gap/quote/view nhất quán ở chat, reader, Markdown/HTML/DOCX.

## Nghiệm thu

Fixture W14 snippet + W3 có 65 nhưng không có 2023: generation không dùng W14 làm primary, repair biết chính xác phần năm thiếu, không mở gate bằng cách giảm kiểm định. Có cả case số thực sự sai, provided vs requested, timeline meeting vs pilot, unknown authority, malformed text và reader có source numbers bị khuyết. Sau tests, replay thực với email đã ẩn và public evidence snapshot, đọc output và ghi pass/fail theo tiêu chí người dùng. Không đưa private inbox lên model, không gửi email, không reset dữ liệu để thử.
