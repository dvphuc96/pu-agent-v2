# Spec: report gọn và đánh giá đúng phạm vi

Trạng thái: đã triển khai và kiểm thử 16/10/2026. Kế hoạch gốc: `../plans/2026-10-16-report-editorial-calibration.md`. Chưa có đánh giá lại Vinamilk/inbox thật.

## Dữ liệu và kiểm định

Giữ report schema v2; rubric tăng v5. Coverage coarse là tỷ lệ nhóm mô tả có bằng chứng, không gọi là mức đầy đủ/chính xác doanh nghiệp. UI chính hiển thị trạng thái khám phá nhu cầu và các giới hạn xác minh; số publisher/URL là số đếm, không hiển thị diversity/overall/readiness %. Các số thô giữ ở diagnostics có version.

Bổ sung preparation_checklist có key, state known/self_reported/unknown/conflicting, summary và source_ids: contact_role, representative_authority, pilot_department, pilot_users, input_documents, source_systems, security_requirements, decision_owner, budget, timeline. Unknown mặc định, không giảm mẫu số. Known/self_reported phải có nguồn sơ cấp, summary được đối chiếu cùng prose. Email chỉ hỗ trợ tự khai về vai trò/quyền đại diện, không tự xác minh employment. Checklist không thay hard gate.

Một hàm tính readiness dùng cả trước/sau semantic verdict. Giai đoạn discovery dựa vào hồ sơ, yêu cầu, câu hỏi họp và liên hệ được quy nguồn; contact chưa có bằng chứng độc lập chỉ được ghi tự khai, không đạt xác minh đầy đủ. Calendar coverage tách khỏi discovery: thiếu Google không tự chặn research. Pilot stage liệt kê các điều kiện còn thiếu từ checklist, không cộng ngân sách vào discovery và không biến trạng thái đủ họp thành đủ triển khai.

Publisher diversity chỉ đếm URL public đúng loại; email/lịch không làm tăng. Không coi nhiều domain là chứng minh độc lập biên tập.

## Hợp đồng biên tập

Report mới sinh ba section chính company_context, email_need, meeting_preparation; recent_updates chỉ khi có bài thực liên quan; contacts/risks/open gaps đi vào một khối open_items qua missing_information và identity warnings. Không sinh lại toàn bộ mười section cùng ý. Summary 60–90 từ, nội dung chính mục tiêu 600–900 từ; chat khoảng 200–350 từ. Các mục có ít bằng chứng được viết ngắn hơn.

Presentation được đóng băng trong metadata.reading_view trước judge/lưu/hash, gồm blocks và open_items. Không viết lại nội dung factual sau judge. Renderer chỉ trình bày view đã lưu; report cũ giữ layout cũ. Evidence/claim vẫn giữ để đối chiếu. Exact duplicate có cùng nội dung/citation chỉ xuất hiện một lần trong view; near-duplicate được báo vị trí cho judge/repair, không tự xóa vì similarity. Cảnh báo identity đầy đủ chỉ ở open_items; header là badge ngắn. Render chat/HTML/print/Markdown/DOCX dùng cùng view; tránh lặp claims như nội dung chính khi đã có prose.

Prompt/judge ưu tiên dữ kiện vận hành/công nghệ có ích cho cơ hội, kỳ và phạm vi số liệu; không đổ tin sản phẩm ngoài chủ đề vào recent_updates. Chưa bổ sung diễn giải tự làm tròn số factual: giữ số nguyên gốc hoặc bỏ khỏi brief nếu không có ích, tránh làm sai hard numeric gate. Vòng repair chung tối đa một lần như hiện tại.

## Thời gian

Đo thời gian backend nhận lượt chat đến khi hoàn tất xử lý, dùng monotonic clock. Lưu response_timing ở metadata lượt chat/envelope, liên kết report IDs qua turn; không thay immutable report. Reader mở từ chat hiển thị timing lượt đó; không có timing tương ứng thì ghi chưa đo tổng. Research/collection chỉ là phase, không cộng phase chồng nhau. Nhiều report trong một turn dùng cùng turn timing, không cộng lại. Không đo network/render phía client. Export giữ phạm vi timing đã biết khi report được đóng băng.

## Nghiệm thu

Fixture tự khai + local-only không hiển thị đã xác minh toàn bộ hoặc 100% sẵn sàng. Website+email+lịch chỉ tính một publisher. Checklist thiếu có trạng thái unknown, không được âm thầm supported. Cùng report giữ view/citation/open warning nhất quán ở mọi format; dữ kiện độc nhất không mất khi dedup. Một vòng repair vẫn chặn mâu thuẫn thật, sai số và nguồn. Fake-clock chứng minh timing không phải tổng cộng phase và tồn tại sau reload chat; report hash giữ nguyên. Model thật/latency thực được đánh giá riêng, không suy ra từ fake provider hoặc test pass.

## Kết quả triển khai

- Rubric v5: checklist con, trạng thái discovery/pilot/xác minh/lịch, cùng hàm readiness/overall trước và sau semantic verdict. Các số coarse giữ trong diagnostics; UI chính dùng trạng thái và số đếm publisher/URL. Không nới ngưỡng hard factual gate.
- Bố cục compact có reading_view đóng băng trước judge/hash, một nơi cho open_items gồm mâu thuẫn có citation. Sửa đổi tạo view mới, không đổi snapshot cũ; render Markdown bỏ side effect thêm metadata. Duplicate exact giữ một bản trong view, near-duplicate chỉ báo vị trí và yêu cầu sửa khi lặp nhiều; xử lý có giới hạn kích thước.
- Tin cập nhật cần bài thực, liên quan và trong cửa sổ 30 ngày; câu hỏi họp cần ít nhất ba câu cụ thể trong brief mới. Prompt yêu cầu năm và chỉ dùng dữ kiện phù hợp cơ hội. Không thêm LLM editor call cố định.
- Thời gian backend lưu ở đúng assistant row/envelope, không ghi thêm vào report. Reader dùng timing của nút/lượt chat tương ứng; khi một report có nhiều lượt tái dùng mà thiếu context cụ thể thì báo chưa đo, không đoán lượt gần nhất. Benchmark thêm --scope backend_response, không trộn phase hoặc đoán cache hit.
- Python: 687 passed, 11 skipped; JavaScript: 31 passed; lint đạt. Có regression cross-format/citation, numeric checklist, unverified contact, product news, câu hỏi chung chung, revision/hash, telemetry theo đúng row và benchmark scope.
- Hai smoke test bằng model cấu hình, cùng tình huống doanh nghiệp/email hoàn toàn giả lập; không inbox thật và không web tool. Cả hai qua judge/gate, role giữ self_reported, authority/ngân sách/người quyết định vẫn unknown, có năm câu hỏi và hai giả thuyết. Mẫu đã được đọc đối chiếu với bằng chứng giả lập. Thời gian 36,706 và 39,277 giây chỉ đo generation/judge trực tiếp, không bao gồm sync/search/chat; không là SLA.
- Giới hạn: mẫu nhỏ, cùng provider/model sinh và chấm; chưa kiểm tra độ chính xác Vinamilk, đa dạng doanh nghiệp hoặc latency end-to-end thực tế. Thay đổi áp dụng cho report mới; không viết lại các report/approval đã lưu. Không thêm UI form checklist, fine-tuning hoặc gửi email tự động.
