# Báo cáo đối tác: chuẩn chất lượng v2

Luồng chat và tác vụ nền dùng chung schema `report-quality-v2`, được đánh giá bằng rubric `report-quality-rubric-v8`. Người dùng không phải chọn nguồn hoặc điền form research: PU đọc email, thu thập thông tin công khai, kiểm tra lịch và viết báo cáo. Lưu tri thức hoặc gửi email vẫn cần phê duyệt đúng phiên bản báo cáo.

“Kiểm tra 10 email gần nhất” dùng cùng inbox briefing, lấy lô N INBOX xuyên ngày thay vì chỉ hôm nay; mặc định 10, tối đa 100. Sync thành công chỉ sử dụng ID trong lô vừa lấy, kể cả khi lô rỗng. Sync thất bại ghi rõ dữ liệu local chưa được xác nhận mới nhất. Bảng overview không thay thế báo cáo có kiểm định và thẻ đính kèm. [Contract và kiểm thử latest inbox](superpowers/plans/2026-10-18-latest-inbox-routing.md).

## Nội dung và bằng chứng

Báo cáo bổ sung quy mô/vận hành, bối cảnh kinh doanh/công nghệ và mục tiêu/câu hỏi chuẩn bị họp. Hồ sơ doanh nghiệp tách khỏi lời tự giới thiệu và yêu cầu trong email. Các đề xuất thử nghiệm phải được nhận diện là đề xuất, không phải cam kết đã được công ty xác nhận.

Checklist gồm website, lĩnh vực, sản phẩm, quy mô, thị trường, bối cảnh công nghệ, liên hệ, yêu cầu, chuẩn bị họp và lịch. Mỗi mục ghi nhận đã có nguồn, chưa tìm thấy, mâu thuẫn hoặc ngoài phạm vi. “Chưa tìm thấy” không tăng độ đầy đủ. Ngoài phạm vi không tự làm giảm mẫu số để tăng điểm.

Collector nghiên cứu theo nhóm thông tin, trích đoạn có liên quan và giữ ngày công bố. Mặc định tối đa 5 truy vấn, 12 lần đọc, 12 trang web và kiểm tra ngân sách thời gian 45 giây giữa các lần gọi. Request đang chạy vẫn chịu timeout riêng của web tool; đây không phải cam kết toàn bộ báo cáo hoàn thành trong 45 giây. Nội dung email không được chép vào truy vấn; chỉ những từ khóa chủ đề công khai nằm trong allowlist được sử dụng.

Nguồn được chuẩn hóa URL, gắn phạm vi công ty và mức bằng chứng full-page/snippet. Tên gần giống không đủ để gộp hai doanh nghiệp. Website công ty và miền email người gửi được lưu riêng; chưa xác minh quyền đại diện là cảnh báo, không phải lý do tự động loại nhu cầu hợp tác.

Query tách `site:domain` khỏi tên doanh nghiệp; tin công khai tìm bằng tên. Collector ưu tiên báo cáo/quan hệ nhà đầu tư, quy mô và công nghệ, giữ lượt đọc cho các chủ đề chưa có nguồn. Trang sản phẩm chi tiết tối đa một lần đọc trong mỗi pass. Các nhãn chủ đề giúp định tuyến, không chứng minh nguồn thật sự hỗ trợ mọi trường. `collection_performance.topic_coverage` chỉ là coverage thu thập; evaluator vẫn đối chiếu nội dung.

PDF chính thức dùng cùng kiểm tra public DNS/IP/redirect, tối đa 2 MB và 60 trang; parser chạy subprocess timeout 8 giây, nội dung tối đa 100k ký tự và giữ số trang. Cần optional dependency `.[sources]` (pypdf). PDF mã hóa, scan không có text, quá giới hạn hoặc thiếu parser không trở thành bằng chứng đã đọc; giữ khoảng trống dữ liệu. Không có OCR tự động cho tài liệu scan trong đợt này.

Summary mới tập trung giới thiệu doanh nghiệp; nhu cầu email, công nghệ/quy mô, gợi ý họp và lưu ý có vai trò riêng. Chat lấy highlights công khai thay vì dùng nguyên email_need/meeting_context làm điểm nổi bật, giữ citation đang dùng kể cả ngoài tám nguồn ưu tiên. Cảnh báo và lịch xuất hiện một lần. Nguồn trong chat dùng nhãn số tường minh để Markdown không tự đánh lại các số bị khuyết.

Từ rubric v5, generation dùng company_context, email_need, meeting_preparation và recent_updates khi có bài thực liên quan. `metadata.reading_view` đóng băng các khối đọc và open_items trước judge/hash; chat, Markdown, HTML/print và DOCX dùng cùng view. Exact duplicate đủ dài được giữ một bản trong view, không xóa raw evidence; near-duplicate có vị trí cho judge/repair. Reader không nhân đôi phần claims trong nội dung chính; đối chiếu ở phần mở rộng/phụ lục. Revision dựng lại view trước kiểm định, không sửa view của report gốc. Render không thêm metadata vào snapshot đang đọc.

Mục cập nhật của brief mới không có bài đã trích, liên quan và có ngày trong 30 ngày sẽ bị yêu cầu sửa, dù judge cho điểm tổng cao. Chuẩn bị trao đổi cần ít nhất ba câu hỏi cụ thể trong brief mới; prompt yêu cầu năm. Hai điều này kiểm tra hợp đồng nội dung, không chứng minh mọi nhận định hoặc câu hỏi đều hữu ích. Judge vẫn kiểm tra toàn prose với nguồn và sự liên quan.

## Đánh giá và phát hành

Rubric v6 bổ sung checklist protocol `preparation_schema_version=2`: `answer_status` phân biệt provided/requested/unknown; `value`, `scope` và `evidence_quote` phải cụ thể và đối chiếu được. Nói muốn bàn bảo mật không cung cấp yêu cầu bảo mật; cuộc họp 45 phút không phải thời hạn pilot. Giá trị từ email vẫn self_reported. Verdict riêng của judge phải xác nhận câu trả lời và phạm vi, nếu thiếu thì giữ unknown. Gap cuối lấy từ assessment này; chỉ nhãn/gap dẫn xuất được cập nhật sau judge, không sinh thêm factual prose.

Generation/routing không dùng snippet hoặc nội dung AI tổng hợp làm nguồn sơ cấp, loại trùng context và giữ snapshot lịch mới nhất. Collector ghi `read_status`/`read_error_code` an toàn; lỗi đọc chỉ xác nhận `page_read_failed`, không suy ra nguyên nhân PDF nếu chưa có bằng chứng. Public source metrics không tính lead chưa đọc. Repair nhận claim/field/refs và số/ngày/đơn vị thiếu; tối đa một lần sửa, chỉ giữ candidate khi giảm blocker thực và bảo toàn dữ kiện thiết yếu. Kết luận phát hành theo gate cuối; semantic passed không ghi đè lỗi cứng. Nguồn của brief mới phải được dùng trong prose hoặc đối chiếu dữ kiện, giữ nguyên số khi lọc; không thêm nguồn để đủ số lượng. Bản xuất có thông báo cả khi snapshot không tìm được lịch trống.

Kết quả kiểm thử và tự đọc mẫu ngày 17/10: [grounded report convergence](superpowers/validation/2026-10-17-grounded-report-convergence.md).

Rubric v7 dùng `preparation_schema_version=3`, bổ sung `partial`/`remaining_gap`: đã biết loại tài liệu nhưng chưa có mẫu, hoặc biết nơi lưu nhưng chưa chọn hệ thống nhận dữ liệu, không bị xóa hết thành unknown. Partial vẫn cần value/quote/scope và verdict; không tăng thành pilot-ready. Quote có dấu ba chấm chỉ được khôi phục khi toàn bộ giá trị cụ thể có thể tìm lại nguyên văn trong nguồn sơ cấp đã trích; không nối fragment, không chấp nhận paraphrase tự suy. Giữ quote model gốc để audit. Nguồn profile ưu tiên hồ sơ/đầu mối trên trang giới thiệu và trang ngôn ngữ cùng domain có thật. Mốc thành lập khác nhau được cảnh báo có citation; không tự gộp pháp nhân hoặc khẳng định chức danh website là xác minh nhân sự hiện tại.

Reader đặt kết luận phù hợp cuộc gặp ở phần đọc chính; checklist giữ partial/value/phần thiếu, còn gate thô, metric và performance nằm trong chi tiết kỹ thuật. Cảnh báo cùng mốc hồ sơ được giữ một bản trong view khi model đã nêu đủ nguồn và các năm. Nguồn xuất Markdown/DOCX giữ số citation và sắp theo số, không tự đánh số lại.

Plan/spec và mẫu kiểm thử: [opportunity-aware brief](superpowers/validation/2026-10-17-opportunity-aware-brief.md).

Rubric v8 dùng chung `numeric-evidence-v2` cho evaluator và diagnostics. Chữ số ASCII/full-width và ngày CJK như `2018年12月` được đọc với vị trí trong nguồn gốc; không thay source text/hash. So ngày theo độ chính xác, không ghép năm/tháng từ những con số rời. Nguồn tháng 12/2018 hỗ trợ năm 2018 nhưng không chứng minh tháng 11 hoặc một ngày cụ thể. Đối chiếu số là điều kiện cần; copyright cùng năm không chứng minh năm thành lập. Verdict ngữ nghĩa phủ định theo claim tiếp tục chặn dù điểm tổng cao. Snippet không được bổ sung bằng chứng cho claim trộn nhiều citation.

Repair phân biệt lỗi nội dung, giới hạn ký hiệu của evaluator và judge không khả dụng. Không viết lại để chữa parser/provider; nếu còn blocker evaluator không thể xử lý và chỉ còn lỗi biên tập thì cũng bỏ vòng viết không thể mở gate. Candidate vẫn nháp chỉ được giữ khi blocker thực giảm, không thêm lỗi cứng và không mất dữ kiện/lịch đã được hỗ trợ; trạng thái là `improved_draft`. Ít finding hơn hoặc đổi claim ID không phải bằng chứng cải thiện. Mâu thuẫn mốc thành lập thuộc hồ sơ; scale chỉ conflicting khi cùng entity/chỉ tiêu/kỳ/phạm vi có dữ kiện không tương thích. Không tự đổi status để mở gate.

Nghiệm thu, mẫu đọc và giới hạn ngày 17/10: [multilingual evidence and repair](superpowers/validation/2026-10-17-multilingual-evidence-and-repair.md).

Reader hiện ngày lập và cảnh báo bản chưa theo policy hiện tại trước nội dung chính; mở phiên bản mới hơn là hành động riêng, không thay snapshot đang duyệt. Popup cho yêu cầu cập nhật qua hàng đợi nghiên cứu và nói rõ nếu worker tạm dừng/chưa có model. Audit nguồn/lịch ghi rõ thời điểm lập báo cáo. Xem [nghiệm thu 18/10](superpowers/validation/2026-10-18-report-snapshot-clarity.md).

- Checklist có trọng số thay việc đếm section có chữ. Không trình bày chỉ số này như phần trăm mọi dữ kiện đã đúng.
- Các metric coarse còn giữ để tái hiện diagnostics; UI chính không gọi chúng là “100% đầy đủ/sẵn sàng”, không hiển thị diversity/overall theo phần trăm. Publisher chỉ tính nguồn công khai sơ cấp và gộp các subdomain của domain doanh nghiệp đã nhận diện; email/lịch không cộng vào diversity. Đây vẫn không là chứng nhận độc lập biên tập.
- `preparation_checklist` ghi contact_role, representative_authority, pilot_department, pilot_users, input_documents, source_systems, security_requirements, decision_owner, budget, timeline với known/self_reported/unknown/conflicting. Unknown mặc định; không tự bỏ mẫu số. Source/summary được kiểm tra; khẳng định từ email vẫn là self_reported. Sai numeric hoặc source ID trong checklist chặn phát hành; thiếu dữ kiện thực vẫn có thể phù hợp cho discovery.
- Một hàm chung tính readiness trước và sau semantic verdict. Discovery xét bối cảnh, yêu cầu, câu hỏi và liên hệ được quy nguồn; lịch tách thành coverage riêng. Pilot liệt kê đầu vào còn cần xác nhận. Contact chưa xác minh không được coi là đầy đủ quyền đại diện; đủ họp lần đầu không có nghĩa đủ chốt triển khai. UI hiện trạng thái và checklist thay cho phần trăm.
- Kiểm tra nguồn sơ cấp, ID không hợp lệ, nguồn chỉ có snippet, trùng claim, quyền đại diện và trạng thái lịch. Kiểm tra từ vựng là bước lọc, không thay xác minh ngữ nghĩa.
- Judge bắt buộc cho mọi report v2, kể cả research thủ công. Judge đọc cả summary, section prose và claims so với trích đoạn; chấm hỗ trợ dữ kiện, đầy đủ, liên quan, sẵn sàng họp và không lặp. Sai số liệu, ngày, đơn vị hoặc ID nguồn là lỗi cứng. Câu dịch/paraphrase không vượt bộ lọc từ vựng cần verdict theo claim cụ thể, không chỉ điểm tổng cao. Claim chưa được hỗ trợ vẫn chặn phát hành dù coverage vượt 80%.
- Semantic review phân biệt `unavailable`, `incomplete`, `failed`, `passed`. Thiếu judge/thiếu tiêu chí giữ nháp; điểm thấp hợp lệ có thể kích hoạt một lần tự sửa. Judge không thể ghi đè lỗi cứng. Ngưỡng mặc định: factual support ít nhất 7/10, các tiêu chí khác ít nhất 6/10, tổng ít nhất 7/10.
- Nguồn công khai, nguồn công khai được trích, tổng số nguồn và số publisher được đếm riêng. Email/lịch không làm tăng số nguồn web. Publisher/domain count là chỉ số đa dạng nguồn, không phải chứng nhận độc lập biên tập.
- Chỉ tin công khai liên quan có ngày công bố được xét độ mới. Email mới, ngày crawl, tin không ngày và tin tương lai không chứng minh công ty có tin mới trong 30 ngày.
- Có tối đa một lần tự sửa, dùng chung ngân sách với sửa JSON. Không thể tự sửa được thì trả nháp có giới hạn rõ; lỗi provider trong lần sửa chất lượng không xóa bản nháp đầu tiên.
- `evaluation.issues` cung cấp code, mức độ, thông báo và hành động bị ảnh hưởng; nhận định thiếu nguồn có claim/source ID để đối chiếu. Đây là lớp giải thích kết quả, không thay quyền gate. Miền người gửi khác email liên hệ công khai của công ty không tự chứng minh mâu thuẫn; generation và repair phải phân biệt lời tự khai, thiếu xác minh và bằng chứng đối lập thực. Không âm thầm đổi trạng thái mâu thuẫn thành đạt.
- Cache báo cáo có phiên bản quality/evidence policy và rubric. Bằng chứng doanh nghiệp có TTL 6 giờ riêng; lịch có TTL 15 phút. Khi chỉ lịch cũ, PU dùng lại bằng chứng công ty, lấy snapshot lịch mới và viết/đối chiếu phiên bản report mới, không tải lại website. Report cũ và phê duyệt cũ không bị thay nội dung. Nguồn đã tắt không được tái sử dụng qua cache.
- Trong bounded workflow (đã thu thập nguồn workspace), năm role email/company/web/calendar/memory định tuyến nguồn có cấu trúc bằng xử lý local, có checkpoint và event `deterministic=true`; không gọi LLM để tạo các bản tổng hợp bị bỏ đi. Thông thường phần research chỉ cần một lần sinh report và một lần judge; classifier và web search là các bước riêng. Không tuyên bố đây là số call tối đa của toàn bộ chat khi có retry hoặc nhiều đối tác.

Nguồn đọc chính là các link đánh số, khoảng 5–8 link khi có đủ nguồn phù hợp. Chat, Markdown, HTML/PDF và DOCX dùng citation presentation chung: số theo URL public xuất hiện đầu tiên, alias dùng cùng số, hyperlink giữ URL thực đã đọc. Citation từ thông tin còn thiếu và mâu thuẫn cũng phải có đích. Citation quan trọng không bị mất khi vượt tám link; các nguồn bổ sung nằm ở phần mở rộng/đối chiếu. Không thêm link ít giá trị để đủ số.

Tin công khai dùng chung metadata `content_kind` và relevance. Chỉ bài thực có dấu hiệu bài viết/ngày/schema được xét là tin; snippet, email, lịch và chỉ tên topic `recent_relevant_news` chưa đủ. Keyword liên quan dùng whole word/phrase, ví dụ `AI` không khớp nhầm `chairman`. Collector resolve requested URL → final URL để merge kết quả redirect an toàn; dừng search khi hết năng lực đọc/sử dụng kết quả và chia ngân sách theo chủ đề.

## Lịch

Chat và research tự động mặc định xét từ hiện tại tới hết Chủ nhật theo giờ Việt Nam. Lịch của người dùng không xác nhận lịch của đối tác. Calendar lỗi không được coi là lịch trống.

Yêu cầu họp rõ cho tuần này/tuần tới trong lời người dùng ưu tiên email; nếu không có thì lấy email mới nhất có yêu cầu họp. Tuần tương đối trong email neo ngày nhận theo múi giờ Việt Nam. Không dùng dòng quote/forward cũ hoặc mốc triển khai pilot làm tuần họp. Phạm vi đã hết hạn, mâu thuẫn hoặc có ngày cụ thể chưa phân giải được giữ unknown, không tự đổi tuần. Chat đọc lịch sau triage, dùng chung một lần đọc cho cùng phạm vi; đối tác khác tuần có snapshot riêng. Tác vụ nền dùng cùng resolver. Cache so start-date/end/duration/scheduling_window bên cạnh slot; không tái dùng report sai tuần chỉ vì cả hai cùng không có slot. Tool cũ không truyền tham số vẫn xét tuần hiện tại.

Snapshot lịch có timestamp, múi giờ và nguồn local/Google. Trình đọc không đề xuất giờ đã qua hoặc snapshot quá 15 phút. Bản tải xuống giữ snapshot gốc và ghi rõ thời điểm kiểm tra. Khi gửi, nếu các giờ đề xuất đã hết hiệu lực, công cụ từ chối trước khi gọi Gmail; cần tạo báo cáo cập nhật và duyệt lại. Công cụ không âm thầm thay nội dung đã được phê duyệt.

Mặc định structured availability chọn tối đa ba slot không chồng, ưu tiên khác ngày/buổi, trong 09:00–12:00 và 13:30–17:30, lead time 60 phút. `AvailabilityPolicy` cho phép caller chỉnh các cửa sổ/lead/giới hạn; chưa có form cấu hình riêng. Coverage phân biệt `local_only`, `google_checked`, `unknown`. Chỉ còn chiều thứ Sáu thì chọn trong chiều đó, không tự chuyển sang tuần sau. Nhánh legacy cũng tránh nghỉ trưa; không dùng nhánh suy luận end từ text để xác nhận lịch trong luồng chat structured.

## Kiểm thử offline

Từ thư mục repository:

```sh
rtk proxy .venv/bin/pytest -q evals/deterministic
rtk proxy node --test evals/deterministic/test_notebook_runtime.cjs evals/deterministic/test_report_reader_quality.cjs
```

Nếu Node không nằm trong PATH, dùng runtime Node đã cấu hình trên máy. Bộ fixture thực thi trong `evals/datasets/report_quality.jsonl` đi cùng runner `evals/deterministic/test_report_quality_v2.py`. Các test dùng nguồn giả lập, không gửi email/inbox thật tới model và không thực hiện gửi email.

## Thời gian và giới hạn kiểm chứng

`metadata.performance` đo workflow nghiên cứu: từng stage, checkpoint reuse, evaluation/repair và usage nếu được observer cung cấp. `metadata.collection_performance` đo riêng thu thập nguồn; tổng latency chat đã có trong metadata hội thoại. Các phạm vi này không được đánh đồng.

Tổng hợp các bản ghi performance đã loại bỏ nội dung nhạy cảm:

```sh
rtk proxy .venv/bin/python evals/benchmark_report_quality.py performance-records.json
```

CLI chỉ đọc JSON/JSONL được cung cấp, tách cold/warm và provider/model, tính p50/p95 bằng nearest-rank. Chỉ tổng hợp bản ghi có scope `research_workflow`; không trộn thời gian end-to-end vào mẫu workflow.

Để đo riêng thời gian backend của cả lượt chat, dùng bản ghi đã ẩn nội dung chứa `response_timing` (hoặc `meta.response_timing`) và:

```sh
rtk proxy .venv/bin/python evals/benchmark_report_quality.py sanitized-turns.json --scope backend_response
```

Timing lượt chat được đo monotonic gồm chờ agent lock và xử lý chính, lưu ở assistant chat row/envelope; không ghi thêm vào immutable report. Reader mở từ nút trong chat nhận timing của đúng lượt, kể cả một report được tái dùng ở nhiều lượt. Không có timing rõ ràng thì ghi chưa đo tổng; không cộng phase hoặc nhân thời gian theo số report. Export chỉ giữ phạm vi thời gian đã có khi report được đóng băng. Cả hai scope benchmark tách nhóm; cache không được ghi nhận là unknown, không đoán từ thời gian. Số này không bao gồm mạng và render client.

Timing backend có lock_wait/session_setup/agent_response. `inbox_phases` là các bước bên trong xử lý yêu cầu: inbox_scan, classification, calendar, partner_reports, approval_preparation và other. Đây là breakdown lồng nhau, không cộng thêm vào duration tổng. App CLI vẫn ghi scope application_response; dashboard ghi backend_response. Bộ đo mới giúp tìm phần chờ ngoài collection/workflow, chưa chứng minh latency thực tế đã giảm hoặc đạt SLA.

Đã thử generation/judge bằng model cấu hình trên hai lượt dữ liệu hoàn toàn giả lập, cùng một tình huống nhỏ; không đọc hoặc gửi inbox thật và không gọi web tool. Cả hai qua gate, giữ unknown/self_reported cho các đầu vào còn thiếu; đã đọc mẫu để kiểm tra câu hỏi, citation và cách phân biệt giả thuyết. Đây là smoke test, không là benchmark chất lượng Vinamilk hoặc đánh giá độc lập: generator và judge dùng cùng provider/model. Chưa có baseline đủ lớn hoặc SLA latency mới.

Chưa công bố SLA hoặc số đo chất lượng thực tế trên inbox/Vinamilk sau thay đổi. Kiểm thử offline chứng minh hành vi của pipeline và các trường hợp đối chứng, không chứng minh mọi câu trả lời model ngoài thực tế đều đúng. Cần đánh giá trên lượt sử dụng thực tế được phép trước khi hiệu chỉnh ngưỡng hoặc quyết định tối ưu concurrency.
