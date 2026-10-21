# Plan: đối chiếu số đa ngôn ngữ và tự sửa đúng nguyên nhân

Ngày: 17/10/2026. Trạng thái: đã triển khai và kiểm thử. Spec: [multilingual evidence and repair](../specs/2026-10-17-multilingual-evidence-and-repair.md). Kết quả và giới hạn: [nghiệm thu](../validation/2026-10-17-multilingual-evidence-and-repair.md).

## Vấn đề và bằng chứng

Ca thật: `report-b6cb4752-de2f-4f8a-aa86-d6c243b5ac23`, báo cáo Saigon Tech sau reset. Không sao chép email cá nhân vào tài liệu hoặc fixture.

- C4 nêu các năm 2014, 2018, 2019 và dẫn W2/W3/W8. Các đoạn nguồn đã đọc chứa những năm này; W8 viết `設立 2018年12月`.
- `_NUMBER_RE` dùng biên `\w`. Chữ Nhật cũng thuộc nhóm này, nên `_number_literals('2018年12月')` và bản chữ số full-width đều trả tập rỗng. Chênh lệch numeric của C4 chỉ là `2018`; đây là ca validator bỏ sót ký hiệu, chưa phải bằng chứng model bịa năm.
- Repair giữ nguyên lỗi cứng C4. Rank trước/sau chỉ đổi số finding cuối từ 4 xuống 3, nhưng `accepted=true`. Số finding tổng quát không đủ làm tiêu chí cải thiện khi blocker chính vẫn nguyên.
- `information_coverage.scale` cũng bị đánh dấu conflicting. Mốc thành lập khác nhau thuộc vấn đề hồ sơ; số dự án/khách hàng có ngưỡng và kỳ khác nhau chưa chứng minh xung đột cùng chỉ tiêu. Sửa parser không tự động giải quyết blocker này.
- Backend: 153,872 giây; scan 8,268; classification 8,965; calendar 0,012; partner_reports 136,166. Workflow nghiên cứu 97,768 giây, gồm viết 39,517; judge 11,895; viết sửa 35,227; judge lại 11,049. Phần partner_reports ngoài workflow còn có thu thập và lưu/xuất; không gọi toàn bộ chênh lệch là thời gian web.

## Thứ tự triển khai

### 1. Regression từ ca thật trước khi sửa

- Tạo fixture tối thiểu từ các đoạn web công khai về mốc thành lập; email/lịch nếu cần đều giả lập.
- Tái hiện C4 và tình huống candidate chỉ giảm finding count. Ghi rõ expected fail hiện tại.
- Bổ sung đối chứng sai năm thực, sai tháng/ngày, sai đơn vị, mã sản phẩm, nguồn snippet và source ID không tồn tại.

### 2. Chuẩn hóa số/ngày dùng chung

- Tách helper đối chiếu số/ngày khỏi evaluator lớn; generation diagnostics và evaluator phải dùng cùng một contract/version.
- Dùng NFKC trên view để đọc, giữ nguyên source text/citation/hash. Nhận chữ số ASCII/full-width và lịch CJK dạng `YYYY年M月[D日]`.
- Giữ độ chính xác year/year-month/full-date: nguồn tháng 12/2018 hỗ trợ năm 2018, không hỗ trợ tháng 11/2018 hoặc ngày cụ thể chưa có.
- Không bỏ biên Unicode trên mọi số; không biến ISO2018, tên sản phẩm hoặc thời lượng thành năm thành lập. Không quy đổi tiền tệ hoặc chữ số Hán tùy tiện.
- Kiểm định ngữ nghĩa vẫn bắt buộc cho quan hệ, chủ thể, kỳ, ngưỡng và ý nghĩa của con số.

### 3. Phân loại nguyên nhân và quyết định có nên tự sửa

- Phân biệt unsupported fact, invalid/unread evidence, semantic/editorial issue, evaluator unavailable/notation limitation và identity conflict.
- Thiếu số trong nguồn thật hoặc thiếu nguồn: được sửa nội dung theo ngân sách hiện tại. Validator/provider không xử lý được: không yêu cầu model viết lại cùng dữ kiện để chữa lỗi công cụ.
- Tính diagnostics một lần, lưu blocker IDs/reason codes rõ ràng. Không thêm vòng LLM để phân loại lỗi.
- Giữ tối đa một generation repair chung với structural repair; không thêm retry hoặc web budget.

### 4. Chọn candidate theo blocker thực

- Candidate qua toàn bộ gate và không mất dữ kiện thiết yếu mới được coi là repaired/released.
- Nếu vẫn là draft, chỉ giữ candidate khi blocker thực giảm, không phát sinh lỗi cứng mới hoặc làm mất dữ kiện đã được hỗ trợ. Ghi trạng thái improved_draft, không repaired.
- Cùng blocker C4 còn nguyên, chỉ ít finding hơn: reject và giữ bản trước. Không dùng số claim ít đi hoặc đổi ID để giả cải thiện.
- Với lỗi thuần biên tập, xét cải thiện biên tập/semantic trực tiếp; không ép phải có lỗi numeric mới được sửa.

### 5. Phân biệt bất đồng hồ sơ với conflict chặn phát hành

- Năm thành lập khác nhau có thể được nghiên cứu và nêu trung thực như giới hạn hồ sơ; không tự chọn một năm hoặc tự xác minh cùng pháp nhân.
- Chỉ gọi scale conflicting khi có bằng chứng không tương thích về cùng entity, metric, period và scope. `50+` và `>150` không tự mâu thuẫn; không chuyển thành số chính xác.
- Giữ chặn khi có identity/source/numeric error thật hoặc conflict thực chưa xử lý. Không đổi status bằng regex để mở gate.
- Tóm tắt tập trung công ty; nhu cầu giữ ở email_need; giới hạn nguồn ghi phạm vi cụ thể thay vì câu “không thực hiện nghiên cứu bổ sung”.

### 6. Nghiệm thu và bàn giao

- Chạy regression → integration orchestration/caching/approval → toàn suite Python/JS và lint.
- Replay model với nguồn công khai và email giả lập, đọc cả bản chính, checklist, nguồn và lịch; không chỉ dựa judge score.
- Ca C4 hợp lệ: numeric gate không chặn nhầm, còn kiểm định ngữ nghĩa và các blocker độc lập vẫn được xét. Ca sai năm thật: tiếp tục chặn dù judge tổng điểm cao.
- Xác nhận call counts và lý do skip/accept repair. Đo cold/warm, generation/evaluation và backend riêng; không tuyên bố đã giảm 153 giây từ timing model-only.
- Bump rubric dự kiến v8 và numeric contract; cache v7 không được tự coi đạt v8. Không sửa báo cáo/phê duyệt đã lưu, không reset database, không gửi email hoặc dùng computer use.

## Điều kiện hoàn thành

1. Không còn false failure do `2018年12月`/full-width trong ca hợp lệ; sai năm/tháng/đơn vị/source vẫn bị chặn.
2. Candidate không còn được chấp nhận chỉ vì giảm finding count khi blocker chính không đổi.
3. Lỗi evaluator xác định được không tiêu thêm một vòng sinh report; giới hạn không xử lý được được nói đúng nguyên nhân.
4. Source disagreement được trình bày đúng phạm vi; không mở gate bằng cách che conflict thật.
5. Có mẫu đọc được, kết quả tests, số call và timing có scope; báo cáo thật chưa kiểm chứng thì không tuyên bố toàn hệ thống đã ổn.
