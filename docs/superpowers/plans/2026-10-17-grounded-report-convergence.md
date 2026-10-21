# Plan: sửa báo cáo từ lỗi thực tế và kiểm thử tới khi dùng được

Trạng thái: đã triển khai và tự đánh giá/sửa tiếp ngày 17/10/2026. Kết quả: [validation](../validation/2026-10-17-grounded-report-convergence.md). Không reset dữ liệu hoặc gửi email. Không dùng computer use.

## Chẩn đoán có bằng chứng

Ca đối chứng: report Vinamilk `report-1230873c-ccd6-4ab1-ac3a-2894736b6404`.

- C2 dùng W14 là snippet 400 ký tự, không phải PDF đã đọc. Chưa biết chính xác vì sao tải/parse PDF thất bại; không suy ra ngay do giới hạn dung lượng/trang.
- C3 chứa số 65 và câu so sánh với năm 2023. W3 có số 65 nhưng không chứa năm 2023. Gate numeric hiện từ chối nguyên câu; chưa có bằng chứng số 65 sai. Cần sửa phạm vi câu và citation, không hạ numeric gate.
- Checklist gọi pilot_users/security_requirements/timeline là self_reported dù summary chủ yếu nói muốn thảo luận, thiếu giá trị cụ thể, hoặc nói lịch họp thay vì thời hạn pilot.
- Chuỗi newline escape tồn tại trong sections đã lưu. Reading view chưa chuẩn hóa kiểu escape này.
- Repair chỉ nhận findings tổng quát, không có chi tiết claim/field/source hoặc số không khớp. Candidate lỗi vẫn có thể thay bản trước mà không so mức cải thiện.
- Các nguồn chưa đọc đầy đủ, không trích hoặc lặp vẫn xuất hiện như nguồn tham khảo chính.

## Thứ tự triển khai

1. Chuẩn hóa prose có kiểm soát ở bước assembly sau JSON parse, trước freeze/hash; không decode tùy tiện URL, regex hoặc toàn JSON.
2. Chỉ đưa nguồn sơ cấp đã đọc vào tập dùng để sinh dữ kiện; giữ snippet như lead để thu thập, không là primary fact. Loại trùng trong context, giữ source map gốc.
3. Checklist tách giá trị cụ thể, trạng thái có câu trả lời và provenance/phạm vi; yêu cầu quote thực. “Muốn bàn về X” là requested, không phải đã biết X. Lịch họp không phải thời hạn pilot.
4. Repair nhận chi tiết claim/field, refs và số/date/unit không khớp. Chọn candidate theo chất lượng và giữ bản ít lỗi hơn; tối đa một lần sinh sửa. Không tăng retry vô hạn hoặc cho judge ghi đè lỗi cứng.
5. Đồng bộ gap/checklist và trạng thái phát hành; user chỉ thấy lý do chính bằng tiếng Việt, diagnostics thô nằm riêng. Nguồn chính chỉ liệt kê nguồn thực sự dùng và có thể đối chiếu, giữ nguyên số citation.
6. Offline tests theo đúng ca lỗi; sau đó real-model replay với nguồn công khai snapshot và email giả lập/ẩn thông tin, không live inbox. Đọc report như người chuẩn bị họp; nếu chưa đạt thì ghi vấn đề cụ thể, sửa và chạy lại trường hợp liên quan.

## Điều kiện dừng và bàn giao

- Report đọc được, không lộ escape, không lặp nguồn/citation, không đưa số liệu snippet lên summary.
- Checklist/gap không mâu thuẫn; requested/unknown không bị tính như câu trả lời đã cung cấp.
- Case có đủ bằng chứng phải phát hành được sau tối đa một repair; case không đủ bằng chứng trả giới hạn trung thực, không cố mở nút duyệt.
- Gate bảo vệ sai số liệu/danh tính/source vẫn hoạt động, kể cả judge cho điểm cao.
- Có bản test đọc được, kiểm tra nội dung thủ công, timing thực theo scope. Không coi test pass hoặc một judge score là xác nhận Vinamilk ngoài thực tế.
