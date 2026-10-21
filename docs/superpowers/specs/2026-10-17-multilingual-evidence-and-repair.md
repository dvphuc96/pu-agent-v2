# Spec: multilingual numeric evidence và blocker-aware repair

Ngày: 17/10/2026. Trạng thái: đã triển khai và kiểm thử. [Plan](../plans/2026-10-17-multilingual-evidence-and-repair.md). [Nghiệm thu và giới hạn](../validation/2026-10-17-multilingual-evidence-and-repair.md).

## 1. Mục tiêu và phạm vi

Sửa false numeric mismatch của C4 trong báo cáo `report-b6cb4752-de2f-4f8a-aa86-d6c243b5ac23`; giữ kiểm định số liệu nghiêm và tránh viết lại khi lỗi nằm ở evaluator. Không hạ ngưỡng, dùng aggregate judge score để bỏ lỗi cứng, hoặc tự thay nội dung đã duyệt.

Schema report vẫn v2, preparation v3. Rubric `report-quality-rubric-v8`, numeric contract `numeric-evidence-v2`. Version được dùng chung ở evaluator, report metadata, cache/reuse, delivery guard và UI; không sửa ngầm snapshot v7.

Phạm vi đầu: chữ số ASCII/full-width; định dạng số thập phân/ngăn hàng nghìn hiện có; lịch CJK dùng chữ số dạng `YYYY年M月` hoặc `YYYY年M月D日`, kể cả viết sát nhãn tiếng Nhật. Không hứa xử lý mọi ngôn ngữ, niên hiệu Nhật, chữ số Hán, OCR nhầm ký tự, đơn vị lớn CJK hoặc chuyển đổi tiền tệ trong đợt này.

## 2. Contract trích xuất số/ngày

Module đề xuất: `pu/reporting/numeric_evidence.py`. Các wrapper hiện có `_number_literals`, `_date_literals`, `_number_units` chuyển sang helper chung để evaluator và repair feedback không lệch nhau.

Mỗi literal nội bộ có:

- `kind`: number/calendar_date/duration/quantity;
- `canonical_value`, `precision` nếu là lịch: year/month/day;
- `unit` và qualifier/ngưỡng nếu được nhận diện; qualifier chưa hiểu phải giữ nguyên raw thay vì suy ra equality;
- `raw_text`, vị trí/đoạn nguồn tương ứng, `notation` và cờ nhận diện chắc chắn;
- source ID được gắn ở bước đối chiếu, không do model tạo.

NFKC chỉ áp dụng trên view trích xuất. Giữ source gốc, URL, quote, source map, report hash và approval snapshot. Nếu cần span map, trả vị trí gốc có kiểm chứng; không giả offset trên chuỗi gốc sau khi normalize độ dài thay đổi. Có giới hạn độ dài input và regex không gây backtracking không giới hạn.

Các token lịch CJK được nhận diện trước, giữ thành cấu trúc kết hợp năm–tháng–ngày, không rút riêng từng số rồi ghép chéo giữa nguồn. Ngày/tháng phải hợp lệ theo lịch. Nguồn có độ chính xác cao hơn có thể hỗ trợ claim thô hơn: tháng 12/2018 hỗ trợ năm 2018; chiều ngược lại không được suy diễn. Không cần claim nhắc cả tháng khi chỉ nhận định năm.

`2018年` trong hồ sơ có thể là năm lịch; `5年` là thời lượng khi ngữ cảnh thể hiện duration, không phải năm lịch. Bằng chứng numeric là điều kiện cần: copyright 2019 không xác nhận thành lập 2019; tên ISO2018 không trở thành bằng chứng năm thành lập. Semantic verdict kiểm tra quan hệ và attribution, không được bỏ qua vì các token tình cờ cùng xuất hiện.

## 3. Diagnostics và repair routing

Mỗi issue có `code`, `cause_category`, `severity`, `source_ids`, `claim_ids/field_keys`, `expected`, `observed`, `notation`, `normalization_version`, `repairable_by_generation` và fingerprint.

Nhóm nguyên nhân:

| Nhóm | Ví dụ | Hành vi |
| --- | --- | --- |
| content_evidence | Sai năm, gán nhầm đơn vị, thiếu citation | Cho phép một repair nội dung khi điều kiện judge hiện có thỏa |
| evidence_unavailable | Chỉ có snippet hoặc nguồn không tồn tại | Chỉ sửa để bỏ/thu hẹp nhận định và ghi giới hạn; không bịa nguồn, không tăng web budget |
| semantic_editorial | Lặp đoạn, thiếu câu hỏi cụ thể, attribution sai | Một repair có feedback đúng chỗ |
| evaluator_limitation | Có bằng chứng rõ về notation chưa được parser hỗ trợ | Giữ draft với lý do kiểm định; không sinh lại report để chữa parser |
| evaluator_unavailable | Judge/provider không có kết quả hợp lệ | Giữ draft, không regeneration |
| identity_conflict | Danh tính có bằng chứng mâu thuẫn | Giữ guard hiện có, không tự gộp entity |

Không được suy ra evaluator_limitation chỉ vì số không tìm thấy. Phải có dấu hiệu notation không xử lý được trong nguồn sơ cấp đã trích. Còn không thì giữ unsupported/unknown. Khi contract đã hỗ trợ ký hiệu đó, ca hợp lệ được kiểm tra bình thường, không cần fallback LLM để đọc con số.

`plan_repair(report, evaluation)` đề xuất trả decision generate/skip, reason, blocker fingerprints và diagnostics. Nếu có cả issue có thể sửa lẫn evaluator limitation, chỉ cho generation khi sửa nội dung còn có ích; không tuyên bố việc đó sẽ chữa evaluator hoặc mở gate khi blocker còn nguyên. Tối đa một generation repair chung với structural repair, không có vòng lặp mới.

## 4. Quy tắc chấp nhận candidate

`select_repair_candidate` dùng evaluation gốc/candidate và contract nội dung, không chỉ tuple kết thúc bằng `len(findings)`.

- Bản qua toàn bộ gate: có thể chọn nếu không rỗng, không mất các dữ kiện kinh doanh thiết yếu và không vi phạm guard.
- Bản vẫn draft: chỉ chọn khi giảm blocker thực, không tạo lỗi cứng mới, không làm tệ các nhóm blocker khác và không phá phần đã có bằng chứng. Ghi improved_draft cùng remaining blockers.
- Blocker chính không đổi, chỉ ít cảnh báo/finding hơn: giữ original với outcome no_improvement.
- Lỗi thuần editorial: dùng tiêu chí editorial/semantic và hợp đồng nội dung để đo cải thiện, không yêu cầu giảm numeric count từ 0.
- Candidate lỗi parse, source invented, bỏ toàn bộ claims, làm mất nhu cầu email/partial đã biết/lịch đúng tuần hoặc tăng lỗi cứng: reject; không ghi đè checkpoint report tốt hơn.

Fingerprint không chỉ dựa C4/C5 vì ID có thể đổi sau generation. Kết hợp loại lỗi, canonical source references và literal/quan hệ lỗi; giữ mapping ID để trình bày. Không drop negation hoặc qualifier khi chuẩn hóa text. Counts theo nhóm là đối chứng bổ sung; đổi câu hoặc chia một claim thành nhiều claim không tự chứng minh đã chữa lỗi.

Metadata đề xuất `quality_repair_result` có decision/reason, accepted, outcome (`released`/`improved_draft`/`no_improvement`/`invalid_candidate`/`skipped`), blockers_before/after, resolved/new/remaining và before/after diagnostics. `accepted=true` không đồng nghĩa release_allowed=true. Stage usage/call counts phản ánh thực tế, không ghi repair_attempt khi không gọi model.

## 5. Conflict và cách trình bày

Giữ từng năm theo đúng trang, không chọn một mốc thành lập thống nhất khi chưa có bằng chứng. Bất đồng hồ sơ có thể được mô tả đầy đủ trong báo cáo discovery; không tự động biến thành conflict của scale hoặc identity. `50+ dự án` và `hơn 150 dự án` là các ngưỡng tương thích có thể thuộc kỳ/phạm vi khác nhau; không được diễn dịch thành hai số chính xác mâu thuẫn.

Scale chỉ conflicting khi bằng chứng thực sự không tương thích về cùng chủ thể, chỉ tiêu, kỳ và phạm vi. Khi chưa đủ căn cứ so sánh, giữ attribution/period hoặc not_found cho phần chưa biết. Không đổi `conflicting` thành `supported` bằng regex để mở gate; semantic review phải đối chiếu lý do, và conflict thật vẫn giữ cơ chế chặn.

Giới hạn nguồn nêu rõ đã đọc những gì và thiếu gì; bỏ câu khái quát “không thực hiện nghiên cứu bổ sung” nếu collector đã research. Tóm tắt chỉ giới thiệu công ty; yêu cầu email nằm ở email_need. Mỗi cảnh báo hồ sơ chi tiết xuất hiện một lần trong view; audit giữ đủ nguồn.

UI phân biệt: lỗi nội dung cần sửa, nguồn chưa đủ, và kiểm định chưa xử lý được ký hiệu. Không ghi “báo cáo sai số liệu” khi chỉ biết validator chưa đọc được notation. Chỉ mở hành động khi gate/rubric hiện tại cho phép.

## 6. Ma trận nghiệm thu tối thiểu

| Ca | Kỳ vọng |
| --- | --- |
| C4: nguồn 2014, `2018年12月`, 2019 | Numeric không còn missing 2018; semantic/field blockers khác vẫn được xét |
| `設立2018年12月`, `２０１８年１２月` | Nhận cùng năm/tháng sau normalize view |
| Claim năm 2017, nguồn chỉ 2018 | Hard numeric failure, aggregate judge cao không được bỏ |
| Claim tháng 11/2018, nguồn tháng 12/2018 | Không match chỉ vì nguồn khác có số 11 |
| Claim ngày cụ thể, nguồn chỉ năm/tháng | Không suy diễn ngày |
| Ngày CJK không hợp lệ | Không canonicalize thành ngày hợp lệ |
| `5年`, mã ISO2018 và copyright 2019 | Không xác nhận thành lập 2018/2019; semantic kiểm tra quan hệ |
| Decimal/grouping/unit VI/EN hiện có | Không hồi quy 1,2 → 12 hoặc sai đơn vị |
| Chỉ có snippet, derived hoặc invalid ref | Không trở thành primary support |
| Các mốc năm được nêu theo từng trang, chưa chọn mốc thống nhất | Giới hạn hồ sơ trung thực, không tự gán scale conflict |
| 50+ so với >150 chưa có cùng kỳ/scope | Không tự kết luận xung đột |
| Conflict cùng metric/period/entity có bằng chứng đối lập | Giữ chặn/giữ giới hạn theo policy, không che bằng câu chữ |
| Rank chỉ giảm finding 4 → 3, C4 vẫn hỏng | Reject candidate, no_improvement |
| Hai blocker giảm còn một, không mất facts và không có lỗi mới | Chỉ improved_draft; không được gọi repaired/released |
| Candidate đổi ID hoặc xóa hết claims | Không được coi hết lỗi nhờ đổi hình thức |
| Judge/parser limitation xác định được | Skip regeneration không có ích, draft đúng nguyên nhân |
| Lỗi numeric thật, một repair loại đúng nhận định không thiết yếu | Có thể qua nếu toàn bộ gate và nội dung còn hữu ích |
| Profile/quote/partial/next-week/calendar cũ | Không hồi quy các sửa rubric v7 |

## 7. Hiệu năng, lưu trữ và bàn giao

Không đặt SLA bằng số giây từ một mẫu. Đối chứng ban đầu là 153,872 giây backend, workflow 97,768 giây với hai generation/hai judge. Ca hợp lệ sau fix không được phát sinh generation repair chỉ vì ký hiệu năm Nhật; normal generation/judge vẫn bắt buộc. Đếm call chính xác trong test, không assert latency máy/network cố định.

Diagnostics dùng chung kết quả đã trích xuất để tránh tính lại hoặc nhồi lặp toàn bộ source text vào repair prompt. Giữ budget input/excerpt; không tăng max_tokens, số truy vấn web hoặc độ song song như cách chữa parser. Timing backend/inbox/collection/workflow vẫn tách scope, không cộng lặp. Đo cold/warm khi có dữ liệu đủ và ghi sample count; không gọi một replay là p95 hoặc benchmark toàn hệ thống.

Nghiệm thu thực thi sau khi anh cho triển khai: chạy tests/lint, replay email giả lập + public snapshots và tự đọc toàn bản xuất/reader. Tạo báo cáo mới dưới rubric mới để anh test; không chỉnh report đã lưu hoặc approval hash, không reset database, không gửi email, không computer use.
