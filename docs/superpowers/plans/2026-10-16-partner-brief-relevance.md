# Kế hoạch sửa chất lượng research và cách trình bày báo cáo đối tác

Ngày: 16/10/2026. Trạng thái: anh đã duyệt; đã triển khai theo spec `../specs/2026-10-16-partner-brief-relevance.md`, kiểm thử offline đạt. Spec ghi rõ phạm vi đợt này và phần chưa kiểm chứng trên model thật.

## Mục tiêu

Từ câu hỏi về email hôm nay, PU tự nhận diện yêu cầu kinh doanh, nghiên cứu đúng công ty và trả briefing giúp người dùng chuẩn bị cuộc gặp. Người dùng đọc và phê duyệt hành động. Chat ngắn, tự nhiên; báo cáo đính kèm sâu hơn, cùng dữ kiện và nguồn. Bản Vinamilk anh cung cấp là ca đối chứng cho lần sửa này.

Kế hoạch kế thừa phần kiểm định và cache đã có; không làm lại toàn bộ. Chưa xác minh các số liệu thực tế về Vinamilk trong bước lập kế hoạch. Chỉ đọc source code và nội dung anh gửi; không gọi lại inbox, model hoặc trình duyệt, không đổi database.

## 1. Những nguyên nhân đã thấy trong code

| Điểm | Bằng chứng | Hệ quả và hướng sửa |
| --- | --- | --- |
| Query quá chặt | `research_plan.build_research_plan` đặt cả domain và tên công ty vào một cụm trong dấu ngoặc kép | Có nguy cơ giảm độ phủ vì trang không chứa nguyên chuỗi này. Tách tìm trong domain và tìm theo tên công ty; kiểm chứng bằng fixture và kết quả thu thập khi triển khai. |
| Link quan trọng bị bỏ hoặc gán sai nhóm | Collector lọc path bằng chuỗi cố định; `topic_for_path` không có bộ phân loại riêng cho investor relations; đường dẫn `/products/...` dễ được chọn | Dùng mục tiêu hồ sơ/quy mô/công nghệ để xếp hạng; bổ sung tên link và loại tài liệu. Không mặc định trang sản phẩm là nguồn có giá trị cao. |
| Ngân sách bị dùng trước khi tìm đủ chủ đề | Đọc trang gốc rồi tối đa sáu detail pages, sau đó mới chia lượt đọc còn lại cho search | Giữ ngân sách riêng cho báo cáo thường niên, vận hành, công nghệ và tin liên quan trước khi đọc thêm danh mục sản phẩm. |
| Prompt yêu cầu summary ôm nhiều nội dung | `evidence.generation_prompt` yêu cầu summary gồm công ty, sản phẩm, lý do liên hệ, bước tiếp theo; public_research chỉ ba bullet công ty/sản phẩm | Tạo cấu trúc nội dung rõ ràng, giới hạn vai trò mỗi phần. Có dữ kiện về quy mô/công nghệ mới được đưa vào điểm nổi bật. |
| Chat ghép lại section | `inbox_chat.inline_report` có nhánh lấy nguyên public_research/email_need/meeting_context; xóa citation nội bộ nhưng giữ dấu câu; nguồn lấy tám mục đầu | Dùng brief có cấu trúc, chọn nguồn có chủ đích, chuẩn hóa dấu câu sau xử lý citation. |
| Cảnh báo chung chung | Chat in câu mâu thuẫn cố định khi có bất kỳ contradiction và dùng một cờ release cho thông báo lưu/gửi | Hiển thị vấn đề cụ thể và hành động bị ảnh hưởng. Phân biệt thiếu dữ kiện, lệch miền người gửi và mâu thuẫn thật. |
| Chỉ lấy đầu mỗi khoảng rảnh | `availability.free_windows` lấy một slot ở đầu mỗi khoảng 09:00–18:00, không loại nghỉ trưa | Trên một ngày còn lại dễ chỉ có 11:30–12:15 dù buổi chiều còn rảnh. Chia theo buổi, xếp hạng và chọn tối đa ba slot. |

Chưa thể kết luận lý do chính xác quality gate chặn bản Vinamilk chỉ từ văn bản chat. Khi triển khai cần đọc evaluation của đúng report để phân biệt lỗi nội dung, nhận diện, lịch hay semantic judge; không nới ngưỡng dựa trên suy đoán.

## 2. Phương án chọn

Chỉ đổi prompt sẽ cải thiện câu chữ nhưng không có thêm bằng chứng. Tăng số trang đọc đồng loạt tốn thời gian và vẫn có thể đọc thêm trang không liên quan. Phương án đề xuất là research theo các khoảng trống bằng chứng, kết hợp biên tập có cấu trúc và kiểm định từng loại lỗi.

Không hard-code Vinamilk. Công ty niêm yết ưu tiên báo cáo và quan hệ nhà đầu tư; doanh nghiệp nhỏ ưu tiên hồ sơ, giải pháp, dự án và khách hàng công khai. Công ty ít dữ liệu được báo rõ giới hạn, không bị ép phải đủ số nguồn hoặc có tin trong 30 ngày.

## 3. Kết quả người dùng sẽ đọc

### Trong chat

1. Tóm tắt email: số email và số cuộc trao đổi cần chú ý, dùng thì đã hoàn thành nếu report đã tạo.
2. Giới thiệu công ty khoảng 70–110 từ, chỉ các dữ kiện công khai có ích.
3. Ba đến năm điểm đáng chú ý: quy mô/vận hành, thị trường và bối cảnh công nghệ phù hợp cơ hội. Không dùng sản phẩm lẻ để lấp mục.
4. Nhu cầu từ email: một đoạn riêng khoảng 40–70 từ, ghi rõ là lời người gửi.
5. Một đề xuất bước tiếp theo hoặc giả thuyết pilot ngắn, có nhãn đề xuất.
6. Một khối lưu ý tập trung nếu cần, nói rõ điều chưa xác minh và ảnh hưởng.
7. Thẻ báo cáo; năm đến tám link nguồn đã dùng nếu có đủ nguồn đạt chất lượng; lịch xuất hiện một lần ở cuối câu trả lời.

Mục tiêu phần nội dung chính khoảng 250–400 từ tiếng Việt, không tính link và lịch. Không cắt máy móc đến mức mất dữ kiện hoặc nguồn.

### Trong báo cáo đầy đủ

- Hồ sơ công ty: lĩnh vực, sản phẩm theo nhóm, khách hàng/thị trường.
- Quy mô và vận hành: chỉ số gắn kỳ báo cáo, đơn vị và phạm vi doanh nghiệp.
- Bối cảnh liên quan cơ hội: công nghệ hoặc đặc điểm vận hành có nguồn; tránh suy ra nhu cầu mua từ việc công ty có tự động hóa.
- Cập nhật liên quan: ngày công bố và ý nghĩa; vắng tin mới thì ghi nhận giới hạn một lần.
- Nhu cầu từ email và người liên hệ, phân biệt tự khai với xác minh.
- Chuẩn bị họp: mục tiêu, khoảng năm câu hỏi ưu tiên, một đến hai giả thuyết pilot và tiêu chí đánh giá đề xuất.
- Lịch, điểm cần xác minh và nguồn.

Nguồn của dữ kiện công khai có citation gần nhận định; lời người gửi dùng nhãn “Theo email”; đề xuất không được diễn đạt như dự án đã được công ty công bố. Chat, reader và export dùng chung dữ liệu và ánh xạ citation.

## 4. Các gói triển khai theo thứ tự

### P0-A — Research đúng trọng tâm

Files chính: `pu/reporting/research_plan.py`, `collection.py`, `source_contract.py`, `pu/tools/web_source.py`.

- Tách query `site:domain` với chủ đề cụ thể và query theo tên công ty; tránh quote chung domain+tên. Giữ bảo vệ dữ liệu riêng tư và kiểm tra đúng thực thể.
- Xếp hạng link theo chủ đề còn thiếu, loại nguồn, độ cụ thể và thông tin mới; dùng title/anchor text khi có. Trang danh sách tin giúp khám phá bài, không thay thế bài thực tế.
- Dành lượt đọc cho hồ sơ, quy mô và công nghệ trước khi đọc sâu sản phẩm. Trang sản phẩm lẻ mặc định tối đa một, chỉ tăng nếu email có nhu cầu liên quan trực tiếp.
- Có bảng evidence coverage cho từng chủ đề và lý do chọn/bỏ nguồn. Không coi snippet hoặc nguồn chưa tải là bài đã đọc.
- Với báo cáo PDF chính thức: trước hết xác minh đường đọc hiện tại. Nếu chưa hỗ trợ, thêm trích xuất có giới hạn bytes/trang/thời gian, giữ kiểm tra URL/redirect, thông tin trang và đoạn trích; lỗi PDF trả khoảng trống minh bạch. Không để một PDF làm treo toàn bộ luồng.
- Hết budget thì trả phần đã xác minh và mục còn thiếu, không tự tăng hạn mức. Dùng chung budget giữa thu thập ban đầu và bổ sung bằng chứng.

Nghiệm thu: fixture Vinamilk có link investor/annual/technology phải chọn được bằng chứng quy mô và công nghệ; không kết thúc với chủ yếu trang kem/sữa chua khi nguồn tốt đã sẵn có. Test thêm doanh nghiệp nhỏ, tên trùng và nguồn lỗi.

### P0-B — Biên tập chat và báo cáo

Files chính: `pu/reporting/models.py`, `evidence.py`, `citations.py`, `pu/orchestration/inbox_chat.py`, reader và các renderer.

- Bổ sung brief có cấu trúc gồm giới thiệu, highlights, email_need, đề xuất và lưu ý; tương thích báo cáo cũ. Không lấy nguyên section dài làm highlight dự phòng cho báo cáo mới.
- Tách dữ kiện công khai/lời người gửi/đề xuất trong hợp đồng generation; hạn chế lặp giữa summary và section.
- Tận dụng bước generate/judge đã có, không thêm một LLM editor call cố định cho mọi report.
- Chọn nguồn theo mức sử dụng và giá trị bằng chứng, giữ nguồn quan trọng dù thu thập sau. Tái dùng citation contract cho cả chat; hiện inline_report còn có logic đánh số riêng.
- Sửa whitespace/dấu câu sau khi thay citation; không nhét bullet vào trong bullet. Giảm cụm citation liền nhau bằng tách nhận định và chọn nguồn hỗ trợ trực tiếp.
- Mỗi cảnh báo một lần; lịch chỉ một lần trong chat. Mâu thuẫn phải nêu cụ thể hai nhận định/nguồn/kỳ dữ liệu; thiếu quyền đại diện không tự biến thành mâu thuẫn doanh nghiệp.

Nghiệm thu: snapshot text Vinamilk không còn lặp ba hướng AI/OCR/đào tạo, cảnh báo hai lần, lịch hai lần, `phòng ban .` hoặc bullet lồng dạng văn bản. Citation trong chat và bản tải cùng trỏ đúng nguồn.

### P0-C — Chẩn đoán chất lượng và quyền thao tác rõ ràng

Files chính: `pu/evaluation/report.py`, `models.py`, `pu/reporting/identity.py`, `pu/tools/report_delivery.py`, approval API và UI.

- Đọc lý do chặn của đúng report trước khi sửa rule. Chấm riêng chất lượng hồ sơ doanh nghiệp và khả năng chuẩn bị cơ hội; không cộng đầy đủ chỉ vì section có chữ.
- Phân loại issue có code, mức độ, source/claim liên quan và hành động bị ảnh hưởng: sai công ty/số liệu, mâu thuẫn thực, thiếu thông tin, quyền đại diện chưa rõ, lịch chưa xác nhận.
- Giữ chặn nhận định không có nguồn, trộn công ty, số liệu sai và giả danh lịch đã xác nhận. Không “chữa” report bằng cách chỉ bỏ cảnh báo hoặc hạ ngưỡng judge.
- Đề xuất tách đọc/tải, lưu bản nháp, lưu như báo cáo đã đạt và gửi. Lưu nháp chỉ bằng hành động riêng, có trạng thái nháp; không dùng chung đường import làm tri thức đã xác minh. Nếu phạm vi UI chưa đủ, tiếp tục giữ chặn lưu bản hoàn tất.
- Lệch miền người gửi chỉ là cảnh báo cần xác minh; kiểm tra bằng chứng danh tính khác trước khi quyết định gửi. Gửi vẫn có approval gắn đúng phiên bản report và kiểm tra lịch mới khi cần.
- Nâng version policy/rubric nếu đổi ý nghĩa tiêu chí; report/cache/approval cũ không tự nhận trạng thái đạt.

Nghiệm thu: email saigon-tech.vn nói về Vinamilk được research đúng Vinamilk; không xác nhận Minh Anh là đại diện nếu chưa có bằng chứng. Báo cáo sai dữ kiện vẫn bị chặn dù câu chữ tốt. UI nói được cụ thể vì sao hành động chưa khả dụng.

### P1-D — Lịch hữu ích trong tuần hiện tại

Files chính: `pu/reporting/availability.py`, `calendar_slots.py` cho nhánh legacy, `pu/orchestration/inbox_chat.py`, renderer.

- Mặc định đề xuất khung 09:00–12:00 và 13:30–17:30, thứ Hai đến thứ Sáu, theo Asia/Ho_Chi_Minh; cấu hình được theo sở thích người dùng. Khoảng nghỉ trưa là chính sách gợi ý, không là sự kiện bận thực tế.
- Sinh nhiều ứng viên từ khoảng rảnh dài, xếp hạng và chọn tối đa ba slot không chồng nhau; ưu tiên khác buổi/ngày, có thời gian chuẩn bị tối thiểu đề xuất 60 phút.
- Chỉ còn thứ Sáu thì chọn trong phần còn lại của thứ Sáu; không tự nhảy sang tuần sau hoặc bịa đủ ba lựa chọn. Không đủ thì báo số lựa chọn thực có và gợi ý xem tuần sau.
- Tách coverage local-only/Google checked/unknown và trạng thái có slot. Local-only ghi rõ lịch chưa được xác nhận đầy đủ, vẫn cho đọc gợi ý. Không nói đã kiểm tra lịch đối tác.
- Giữ snapshot TTL, từ chối lịch quá khứ, lỗi đọc lịch và kiểm tra lại trước hành động gửi có thời gian họp.

Nghiệm thu: tại 11:08 thứ Sáu 16/10/2026, ngày không có sự kiện phải có lựa chọn buổi chiều; không đề xuất 11:30–12:15 cắt qua nghỉ trưa. Test sát cuối ngày, cuối tuần, busy/all-day, timezone và Google lỗi.

### P1-E — Vòng bổ sung có giới hạn và đo hiệu quả

Files chính: `pu/orchestration/research.py`, `pu/reporting/performance.py`, cache/policy và bộ eval.

- Judge trả lỗi có cấu trúc: thiếu bằng chứng thì có thể tìm thêm đúng chủ đề; lỗi câu chữ thì viết lại; không sửa mù hoặc chạy lại toàn bộ.
- Tối đa một vòng cải thiện tổng cộng; dùng chung ngân sách thời gian, số trang, token và số lần generation với JSON repair hiện có. Judge cuối vẫn quyết định trạng thái.
- Cache bằng chứng công ty và lịch tiếp tục tách biệt. Bump version cache khi đổi cách chọn nguồn/nội dung; không làm mới web chỉ vì lịch hết hạn.
- Đo số request thực, lượt đọc hữu ích, thời gian từng phase và end-to-end. So sánh cùng provider/model/dataset, tách cold/warm. Không cam kết 42 giây hoặc số chính xác khi chưa đo.

## 5. Bộ kiểm thử và trình tự nghiệm thu

1. Tạo đối chứng đầu vào, evidence và đầu ra tốt/xấu từ bản Vinamilk anh gửi, ẩn dữ liệu cá nhân. Bổ sung doanh nghiệp nhỏ, tên trùng, không có tin mới, chỉ có PDF và nguồn mâu thuẫn khác kỳ.
2. Sau P0-A/B, kiểm tra nguồn đúng trọng tâm và đọc bản chat/report mẫu cạnh bản cũ. Model giả kiểm tra hợp đồng; không dùng nó để tuyên bố chất lượng model thật.
3. Sau P0-C/D, kiểm tra ma trận hành động, identity, citation/hash approval, ngày giờ và các trường hợp thiếu dữ liệu.
4. Chạy bộ Python/JavaScript phù hợp và lint, giữ các regression đã có về số liệu, redirect, cache và giới hạn repair.
5. Đánh giá model thật trên dữ liệu đã ẩn hoặc dữ liệu anh cho phép; lưu cấu hình, lý do gate và latency. Đọc thủ công các bản đạt/bị chặn để phát hiện false pass/false block.
6. Report kết quả cho anh với mẫu đầu ra thực tế, phần chưa đạt và số liệu đo; không reset data hoặc gửi email để nghiệm thu nếu anh chưa yêu cầu.

Tiêu chí chốt: đúng công ty, dữ kiện có bằng chứng, không dùng nguồn sản phẩm để lấp nghiên cứu doanh nghiệp, briefing có ích cho cuộc họp, cảnh báo cụ thể một lần, nguồn mở được và đúng nội dung trích, lịch trung thực/phù hợp, hành động phê duyệt không mất bảo vệ. Không đặt mục tiêu số nguồn cao hơn mục tiêu chất lượng.

## 6. Ranh giới và các quyết định đề xuất

- Triển khai P0-A → P0-B → P0-C, rồi P1-D → P1-E. Chốt hợp đồng brief/issue trước khi thay UI; chỉ chạy vòng bổ sung sau khi đã đo phần thu thập cơ bản.
- Không ép thêm lãnh đạo, tài chính hoặc tin 30 ngày vào mọi doanh nghiệp. Chọn nếu có bằng chứng và có ích cho cuộc gặp; tài chính phải có kỳ, lãnh đạo phải đúng chức danh và thời điểm.
- Không diễn giải “chưa thấy mâu thuẫn” thành “đã chứng minh mọi dữ kiện đúng”. Không dùng phần trăm accuracy từ điểm LLM.
- Nhận xét trước đây rằng chỉ nên khóa gửi là quá rộng: report có sai dữ kiện nghiêm trọng vẫn phải chặn lưu như bản hoàn tất. Kế hoạch này giữ ranh giới đó và chỉ đề xuất thêm lưu nháp có nhãn rõ.
- Chỉ thay code sau khi anh duyệt kế hoạch; không có bước người dùng phải tự điền checklist research trong luồng chính.
