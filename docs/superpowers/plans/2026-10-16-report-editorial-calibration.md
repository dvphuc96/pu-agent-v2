# Kế hoạch tiếp theo: briefing gọn và đánh giá đúng ý nghĩa

Ngày: 16/10/2026. Trạng thái: anh đã duyệt và đã triển khai theo `../specs/2026-10-16-report-editorial-calibration.md`; spec ghi kết quả kiểm thử và giới hạn kiểm chứng.

Đầu vào đối chứng: bản Vinamilk anh gửi sau lần triển khai rubric v4, có nguồn nhà đầu tư/báo cáo thường niên, nhiều phần lặp, coverage/readiness 100%, một publisher công khai và hai phạm vi thời gian riêng.

## 1. Mục tiêu và giới hạn

Báo cáo phải giúp anh bước vào buổi trao đổi với hiểu biết đúng về đối tác, nhu cầu người gửi và những câu hỏi cần làm rõ. Phần đánh giá phải nói chính xác hệ thống đã kiểm tra điều gì, không biến một phép đếm coverage thành xác nhận đã đủ thông tin hoặc chính xác tuyệt đối.

Giữ luồng tự động: hỏi inbox → nhận diện cơ hội → research → đọc report → duyệt hành động. Không thêm form checklist bắt người dùng điền. Kế thừa collector, PDF, citation, immutable report, cache và mandatory judge đã có. Bước lập kế hoạch không tra cứu lại số liệu Vinamilk, gọi model, gửi inbox ra ngoài hoặc khởi động lại dashboard.

Điều chỉnh nhận xét trước: thiếu ngân sách/phòng ban/quyền đại diện không có nghĩa mọi báo cáo đều không đủ để họp lần đầu. Ngược lại, một mục ghi “chưa xác minh” có nguồn không chứng minh thông tin đó đã được xác minh. Kế hoạch tách hai ý nghĩa này, không ép mọi cơ hội mới phải đạt đầy đủ hồ sơ giao dịch.

## 2. Nguyên nhân xác nhận trong source hiện tại

| Điểm | Vị trí | Vấn đề thực tế |
| --- | --- | --- |
| Coverage nhóm lớn | `pu/evaluation/report.py`, `_evaluate_v2` | Mười nhóm được tính supported theo summary/source. Một summary chứa cả điều biết và điều chưa biết vẫn có thể khiến cả nhóm được tính đủ. |
| Readiness quá thô | `_evaluate_v2`, `_apply_pending_verdicts` | Cộng request 30%, meeting_preparation 30%, contact 15%, calendar 25%; contact tự khai và lịch local có thể giúp lên 100% mà người đọc tưởng đã xác minh đầy đủ. Công thức lặp ở hai nơi, dễ lệch khi sửa. |
| Diversity khác tên hiển thị | `_evaluate_v2` | Đếm lớp domain/source_type của mọi nguồn sơ cấp rồi chia ba; website + email + calendar có thể đạt 100%. Đây không phải đa dạng publisher công khai. |
| Trùng prose chưa được kiểm tra đủ | `_evaluate_v2`, generation prompt | Duplicate metric chủ yếu so normalized text của claim; summary và các đoạn section lặp ý không được đo riêng. Judge có tiêu chí nondup nhưng trường hợp thực vẫn qua. |
| Bố cục chia quá nhiều phần gần nhau | `evidence.py`, `render.py`, `docx.py`, `inbox-chat.js` | company/public_research/company_scale/business_context và meeting_context/meeting_preparation/risks_opportunities dễ nhắc lại cùng thông tin. |
| Cảnh báo không có một nơi hiển thị chuẩn | identity metadata, prose, missing_information, evaluation warnings và renderer | Chỉ yêu cầu model không lặp không ngăn được cảnh báo xuất hiện đồng thời trong nhiều lớp giao diện. |
| Thời gian tổng chưa ở report reader | `app.py`, `dashboard.py`, `performance.py`, `inbox-chat.js` | Chat đã có latency; report reader hiện chủ yếu hiển thị research_workflow và source_collection riêng. Hai số này không phải số đo end-to-end. |

Các số liệu cụ thể về Vinamilk trong bản anh gửi chưa được xác minh ngoài nguồn ở bước này. Không kết luận nguồn sai chỉ vì report trình bày chưa tốt.

## 3. Thiết kế kết quả người dùng sẽ đọc

### Bản chat

Khoảng 200–350 từ phần nội dung chính, không tính link/lịch: giới thiệu ngắn, ba điểm có ích cho cơ hội, nhu cầu từ email, bước tiếp theo, một lưu ý tập trung nếu cần. Khoảng 5–8 nguồn thực sự có giá trị khi có đủ; giữ mọi nguồn đang trích. Lịch xuất hiện một lần.

### Báo cáo đính kèm

Một phần tóm tắt khoảng 60–90 từ; nội dung chính mục tiêu khoảng 600–900 từ tiếng Việt, điều chỉnh nếu bằng chứng cần giải thích. Tổ chức thành sáu khối:

1. Công ty và bối cảnh liên quan: hồ sơ, quy mô/thị trường và công nghệ phục vụ cuộc gặp; mỗi ý quan trọng có một nơi trình bày chính.
2. Nhu cầu từ email: mục tiêu và phạm vi do người gửi nêu, không diễn đạt thành nhu cầu đã xác nhận của doanh nghiệp.
3. Chuẩn bị trao đổi: một mục tiêu cuộc gặp, năm câu hỏi ưu tiên và tối đa hai giả thuyết pilot có tiêu chí đề xuất.
4. Điểm chưa xác minh: một nơi tập trung cho người liên hệ, dữ liệu, quyết định và rủi ro; tách dữ kiện mâu thuẫn thật khỏi điều chưa biết.
5. Lịch: phạm vi, thời điểm kiểm tra và số lựa chọn thực có.
6. Nguồn: tên dễ hiểu, kỳ tài liệu nếu đã xác minh được, link và citation thống nhất.

Tin mới chỉ thành một khối riêng nếu có tin đúng công ty và có ích cho cơ hội. Không có thì một câu trong giới hạn nghiên cứu, không dựng đoạn dài về tin sản phẩm ngoài chủ đề. Evidence và đối chiếu kỹ thuật vẫn truy cập được ở phần mở rộng.

## 4. Gói A — Sửa hợp đồng đánh giá trước (P0)

### Tách bốn điều đang bị gộp

- **Có bằng chứng cho điều đang nói:** claim/prose đã đối chiếu, nguồn và phạm vi hỗ trợ; đây không phải phần trăm đúng ngoài thực tế.
- **Đã biết những gì:** coverage theo các dữ kiện con, có trạng thái known/self_reported/unknown/conflicting và lý do. Self-reported có thể hỗ trợ câu “người gửi tự giới thiệu…”, nhưng không hỗ trợ câu xác nhận việc làm/quyền đại diện.
- **Đủ để làm gì:** mức sẵn sàng theo giai đoạn cuộc trao đổi.
- **Phạm vi đã kiểm tra:** lịch local/Google, kỳ số liệu, ngày xuất bản và nguồn độc lập.

Đề xuất checklist con tối thiểu:

| Nhóm | Phân biệt cần lưu |
| --- | --- |
| Liên hệ | Tên/email được cung cấp; vai trò tự khai; quyền đại diện đã/chưa xác minh. |
| Nhu cầu | Bài toán; phạm vi mong muốn; người dùng/phòng ban; dữ liệu hoặc tài liệu đầu vào đã biết/chưa biết. |
| Chuẩn bị họp | Mục tiêu; câu hỏi gắn khoảng trống cụ thể; giả thuyết đề xuất và điều kiện cần xác nhận. |
| Quy mô | Chỉ tiêu có ích cho bối cảnh; đơn vị; năm/kỳ; phạm vi công ty/nhà máy/thị trường. Có vốn điều lệ không tự tương đương có đủ dữ kiện vận hành. |
| Lịch | Phạm vi nguồn đã đọc; đọc thành công hay lỗi; độ mới snapshot; slot hợp lệ. Chưa đọc Google không được coi là đã kiểm tra toàn bộ lịch. |

Không để LLM tự đặt mục unknown thành not_applicable để tăng điểm. Not-applicable chỉ theo policy có lý do, giữ mẫu số công khai và so sánh được.

### Sẵn sàng theo mục đích

- “Đủ để trao đổi khám phá”: đúng công ty, có yêu cầu kinh doanh và thông tin liên hệ được quy nguồn, có bối cảnh và câu hỏi hữu ích; chỉ rõ điều còn thiếu.
- “Cần bổ sung để xác định pilot”: chưa rõ phạm vi, dữ liệu, đầu mối quyết định hoặc điều kiện bảo mật. Không coi đây là hồ sơ sẵn sàng ký/chốt triển khai.
- “Chưa đủ tin cậy”: sai thực thể, nhận định thiếu bằng chứng quan trọng, mâu thuẫn thực chưa giải quyết hoặc judge chưa hoàn tất.

Không thêm lời hứa “100% sẵn sàng” cho cả ba giai đoạn. Quyền gửi/lưu vẫn tuân thủ gate và approval; không suy ra quyền tự động từ nhãn sẵn sàng. Report chưa xác minh quyền đại diện không tự bị coi là giả mạo hoặc tự bị loại khỏi giai đoạn khám phá.

### Sửa diversity và cách hiển thị điểm

- Hiển thị số URL đã đọc, số URL dùng làm bằng chứng và số publisher công khai riêng. Email/lịch không tăng publisher diversity.
- Không hiển thị tỷ lệ “đa dạng nguồn 100%”. Một publisher chính thức có thể phù hợp; không buộc đi tìm báo ngoài chỉ để tăng điểm. Domain count không được tuyên bố là bằng chứng độc lập biên tập.
- Đổi tên coverage cũ hoặc giữ trong phần kỹ thuật với mô tả đúng: không trình bày như phần trăm đầy đủ về doanh nghiệp. Bỏ điểm tổng 95% khỏi lớp thông tin chính khi chưa có hiệu chỉnh đối chứng; giữ raw diagnostics có version để phân tích.
- Tập trung tính toán vào một hàm/shared contract, được gọi sau deterministic check và sau semantic verdict; không để hai nhánh readiness/overall khác nhau.
- Version schema đánh giá/rubric và cache khi đổi ý nghĩa. Report cũ giữ nguyên, hiển thị chuẩn cũ/chưa đánh giá lại; không tự chuyển thành đạt và không đổi hash approval.

Nghiệm thu: bản đối chứng có contact tự khai và local-only không thể hiện như đã xác minh đầy đủ; website+email+lịch không thành ba publisher; các hard gate hiện hành vẫn chặn sai số/nguồn/danh tính.

## 5. Gói B — Biên tập bằng cấu trúc và một nơi hiển thị (P0)

- Thiết kế mapping từ section chuẩn hiện tại sang sáu khối đọc; giữ tương thích report cũ và evidence. Bản mới có hợp đồng section-role rõ, tránh sinh ba phần cùng mô tả công ty.
- Mỗi cảnh báo có code/subject ổn định; renderer chỉ trình bày đầy đủ ở khối “Điểm chưa xác minh”. Header dùng một badge ngắn, không lặp nguyên đoạn. Trong phần chất lượng, chỉ dẫn đến khối lưu ý hoặc nêu số vấn đề mới, không chép lại toàn bộ.
- Không xóa mọi câu có chữ “đại diện” hoặc “chưa xác minh” bằng substring; có thể mất rủi ro khác. Chuẩn hóa/dedup theo issue và nội dung có nguồn; giữ thông tin độc nhất.
- Thêm kiểm tra trùng đoạn/ý giữa summary và section, không chỉ claim. Exact/near-duplicate là tín hiệu để sửa, không tự xóa đoạn hoặc citation theo một điểm similarity.
- Judge phải chỉ ra vị trí lặp, nguồn/câu thiếu phạm vi và nội dung ngoài trọng tâm. Dùng vòng repair chung hiện có, tối đa một lần; không thêm editor LLM call cố định cho mọi report.
- Thứ tự đúng: dựng nội dung → kiểm định/repair → dựng presentation → lưu phiên bản/hash → phê duyệt. Không viết lại hoặc thay nội dung factual sau judge hay sau approval để làm giao diện gọn hơn.
- Dùng cùng presentation contract cho chat, reader, Markdown, HTML/PDF và DOCX; không chỉ sửa modal rồi để bản tải vẫn dài/lặp.

Nghiệm thu: cảnh báo quyền đại diện chỉ có một bản mô tả đầy đủ trong mỗi bản đọc/export; summary được phép nhắc ngắn một ý chủ chốt, nhưng không lặp nguyên cụm đoạn. Lịch và nhu cầu email không bị chép sang nhiều mục.

## 6. Gói C — Chọn dữ kiện và tin tức theo giá trị cuộc gặp (P1)

- Mỗi highlight giải thích được nó giúp hiểu cơ hội hoặc đặt câu hỏi nào. Ưu tiên vận hành, hệ thống dữ liệu/tài liệu, thị trường và quy mô liên quan; không chọn số liệu chỉ vì có nhiều chữ số và nguồn rõ.
- Vốn/cổ phần/chi tiết kỹ thuật vẫn được giữ trong evidence hoặc phụ lục khi cần; chỉ đưa vào briefing chính khi có lý do phù hợp với cuộc gặp. Không tự ép thêm doanh thu/lãnh đạo nếu không có nguồn và không có ích.
- Với số liệu lớn trong narrative, có thể trình bày gọn theo đơn vị phù hợp nhưng phải lưu số gốc và quy tắc làm tròn; kiểm định hiểu đây là xấp xỉ, không coi số đã làm tròn là dữ kiện chính xác tuyệt đối mới.
- Kiểm tra kỳ và phạm vi cùng nhận định: “nhà máy/hệ thống tự động hóa” không tự trở thành “toàn bộ Vinamilk tự động hóa 100%”. Tin thị trường không tự trở thành kết quả tăng trưởng riêng của công ty.
- Tin mới cần article thực, ngày công bố xác định và quan hệ với cơ hội; trang danh sách tin hoặc tên chủ đề chung chưa đủ. Tin sản phẩm không liên quan không đi vào briefing chỉ để đủ mục.
- Tên nguồn ưu tiên title thật và kỳ tài liệu xác minh được. Không đổi “GROWTH RE:INVENT” thành “Báo cáo thường niên 2024” nếu chưa có bằng chứng xác nhận năm/loại tài liệu.

Nghiệm thu: fixture có tin sản phẩm mới và tin chuyển đổi số phù hợp phải ưu tiên tin liên quan; không có tin liên quan vẫn có thể nhận briefing hữu ích, với giới hạn nêu ngắn gọn.

## 7. Gói D — Đo thời gian người dùng thực sự chờ (P1)

- Đo monotonic từ lúc backend nhận câu hỏi đến lúc hoàn tất trả kết quả; tách sync, classification, availability, collection, generation, judge/repair và persistence. Tách thời gian backend với network/render mà backend không đo được.
- UI ưu tiên tổng thời gian của lượt chat; thời gian từng report/workflow/collection đặt trong chi tiết. Nhiều đối tác có nhiều report dùng cùng turn ID; không gán toàn bộ thời gian chat cho từng report rồi cộng lại.
- Không cộng bừa 39,29 và 46,13 thành tổng nếu chưa chứng minh hai khoảng không chồng và chưa tính phần còn lại. Có tổng đo thực thì dùng tổng; không có thì ghi chưa đo tổng.
- Gắn timing end-to-end ở turn hoặc execution envelope liên kết report ID, không chèn thêm sau lưu vào nội dung report đã hash/phê duyệt. Bản export chỉ dùng timing đã biết trước thời điểm đóng băng hoặc ghi rõ phạm vi đo.
- Ghi trạng thái cache/retry, tách lượt thành công/lỗi; p50/p95 theo cùng model/provider/cấu hình và cold/warm. Chưa đặt SLA mới trước khi có mẫu đo.

Nghiệm thu: UI không gọi research_workflow là tổng thời gian tạo; test injected clock kiểm tra cache, retry, hai report trong một turn và thời gian phase chồng nhau.

## 8. Trình tự triển khai và kiểm thử

1. Chốt spec dữ liệu đánh giá và mẫu sáu khối đọc, lập fixtures từ bản Vinamilk đã ẩn dữ liệu cá nhân. Chọn bản tốt/xấu đối chứng trước khi đặt ngưỡng.
2. Làm gói A, với tests chống cộng điểm unknown/self-reported sai nghĩa, thiếu Google, publisher một miền và hard gates. Kiểm tra cả sau semantic verdict.
3. Làm gói B trên cùng fixtures, kiểm tra chat/reader/export, citations và immutable hash. Đọc bản xuất để kiểm tra flow, không chỉ đếm keyword trong snapshot test.
4. Làm gói C và D; kiểm tra phạm vi số liệu, độ liên quan của tin và thời gian đúng phạm vi.
5. Chạy Python/JavaScript/lint phù hợp và regression source/PDF/cache/approval hiện có. Tests fake model chỉ chứng minh hợp đồng và đường đi, không chứng minh prompt đã cải thiện chất lượng model thật.
6. Trước khi tuyên bố hoàn tất chất lượng: dùng một tập đầu vào đã ẩn hoặc được phép gồm công ty lớn, doanh nghiệp nhỏ, dữ liệu ít, tên gần giống và nguồn mâu thuẫn. Đọc đánh giá thủ công theo rubric; lưu ít nhất các bản failed/pass, đầu ra model và lý do sửa. Không gửi inbox thật ra model chỉ để thử khi chưa có quyền phù hợp.
7. Gửi anh bản trước/sau, spec cuối, kết quả test và hạn chế. Không reset data trong đợt triển khai trừ khi anh yêu cầu.

## 9. Điều kiện bàn giao

- Bản mới đọc gọn hơn bản đối chứng, không mất bằng chứng quan trọng hoặc citation đang dùng.
- Các trạng thái coverage/xác minh/readiness có ý nghĩa riêng; không quảng bá phần trăm “đúng” hoặc “sẵn sàng” từ phép đếm coarse fields.
- Đủ để khám phá nhu cầu được phân biệt với đủ để chốt pilot; không bắt đầu mối mới cung cấp đủ ngân sách hoặc kết nối Google mới được research.
- Cảnh báo một nơi, câu hỏi họp cụ thể, pilot là đề xuất, tin ngoài chủ đề không chiếm chỗ.
- Có thời gian end-to-end thật hoặc ghi rõ chưa đo; không suy diễn từ một phase.
- Lỗi factual/identity/source/calendar và approval binding vẫn được bảo vệ. Không hạ ngưỡng để bản Vinamilk trông đẹp hơn.

Phạm vi chưa thay đổi trong kế hoạch này: kết nối tài khoản, model training/fine-tuning, OCR PDF scan, nút lưu nháp riêng và tự gửi email. Đây là sửa chất lượng báo cáo và đánh giá, không là huấn luyện lại model.
