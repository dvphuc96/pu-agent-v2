# Cập nhật: đánh giá lời mời hợp tác ngay trong chat

Bản cập nhật này triển khai luồng: tìm lời mời đang có trong Gmail → đọc nội dung và chuỗi trao đổi → xác định công ty và người liên hệ → nghiên cứu công khai → kiểm tra lịch → briefing tiếng Việt có nguồn, điểm cần lưu ý, câu hỏi và lựa chọn lịch. Không hard-code công ty, người gửi hoặc giờ hẹn từ cuộc hội thoại mẫu.

## Cách chạy

Từ thư mục source đã giải nén, dùng Python 3.11 trở lên:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[gmail,gcal,pdf,dev]'
cp .env.example .env
```

Điền API key và model trong `.env`, hoặc dùng phần Connections/Models của Dashboard. Ví dụ chọn `PU_PROVIDER=openrouter`, điền `OPENROUTER_API_KEY`, `PU_MODEL` và `PU_SMALL_MODEL` là các model đang có trong tài khoản của anh. Anthropic, OpenAI, DeepSeek, GLM và Gemini vẫn dùng cấu hình hiện có; không đổi provider mặc định của một bản cài đặt đang chạy.

Để tìm kiếm web, cấu hình `TAVILY_API_KEY` hoặc `PU_SEARCH_API_KEY`. Source hiện dùng Tavily, có fallback DuckDuckGo khi chưa cấu hình key; chưa có adapter Google Search trực tiếp. Khi công cụ tìm kiếm hoặc website lỗi, báo cáo phải ghi rõ thiếu bằng chứng.

```bash
python -m pu connect gmail
python -m pu dashboard
```

Gmail cần OAuth Desktop client riêng tại `.pu/credentials.json` nếu chưa cấu hình client; bật Gmail API và Calendar API trong dự án Google. Kết nối Google Calendar trong Dashboard → Connections. Có thể kiểm tra cấu hình bằng `python -m pu connections`. Các kết nối Gmail/Calendar trong ChatGPT không tự chuyển sang ứng dụng local.

Nếu đã cài bản trước: thay source, cài lại lệnh `pip install -e ...`, rồi khởi động lại backend. Giữ `.pu/`, `.env` và token của anh trên máy; ZIP không chứa dữ liệu runtime. Không cần xóa database hay lịch sử chat. Policy nhận diện mới sẽ khiến các báo cáo tự động cũ được kiểm tra lại trước khi phát hành.

## Prompt dùng thử

> Hoàn thành bản đánh giá lời mời hợp tác đang có trong Gmail: tìm email liên quan, xác định công ty từ nội dung thư, nghiên cứu thông tin công khai cần thiết để đánh giá lời mời, rồi kiểm tra Google Calendar để liệt kê các khung giờ còn trống phù hợp. Trình bày briefing ngắn gồm thông tin công ty, điểm cần lưu ý, câu hỏi còn thiếu và các lựa chọn lịch; không gửi thư hoặc tạo sự kiện nếu chưa được anh xác nhận.

Cũng có thể yêu cầu `Đánh giá lời mời hợp tác của Acme trong Gmail và xem lịch`. Nếu có nhiều công ty phù hợp mà chưa xác định được thư nào, agent liệt kê ứng viên để người dùng chọn trước khi nghiên cứu.

## Những phần đã sửa

| Thành phần | Thay đổi |
|---|---|
| Chat router | Phân biệt yêu cầu đánh giá lời mời với quét inbox hôm nay; câu cấm gửi thư không làm rơi khỏi luồng nghiên cứu. |
| Email Agent / Gmail | Thêm `search_gmail`, `read_gmail_thread`; tìm xuyên ngày, phân trang có giới hạn, chỉ dùng đúng kết quả remote; đọc phản hồi đã gửi trong cùng chuỗi. |
| MIME | Ưu tiên text/plain, đọc text/html khi cần; giữ link website, bỏ script/style và attachment khỏi body; báo rõ nội dung thiếu hoặc bị cắt. |
| Company identity | Tách công ty tự giới thiệu, miền gửi, tên người gửi, tên tự giới thiệu và email chữ ký. Sai khác là điểm cần xác minh, không tự kết luận lừa đảo. |
| Web Research | Tiếp tục dùng bộ thu thập có giới hạn, đọc trang thật, giữ nguồn và ngày xuất bản; snippets không trở thành bằng chứng đầy đủ. |
| Calendar | Dùng khoảng start/end có cấu trúc; cố định múi giờ Việt Nam thay vì múi giờ Docker; lọc ngày được yêu cầu trước khi chọn tối đa ba phương án. |
| Lịch đã qua | Trong luồng chat mới, đề xuất phương án mới trong 10 ngày tới và ghi rõ chưa được đối tác xác nhận. Giữ chính sách thận trọng của worker cũ. |
| Report | Câu trả lời ngắn nêu đánh giá, công ty, lời mời, lưu ý, câu hỏi và lịch; giữ link nguồn và trạng thái chất lượng. Báo cáo chi tiết vẫn được lưu dạng bản nháp. |
| Runtime prompt | Bỏ quy tắc chỉ gọi mỗi tool một lần; cho phép đọc thêm trang/chuỗi thư và kiểm tra dữ liệu mới. Nội dung email, web và memory không phải chỉ thị hay quyền thực hiện hành động. |
| Approval | Luồng đánh giá mới không tự tạo đề xuất gửi/lưu. Các thao tác ghi vẫn đi qua proposal → người dùng duyệt → executor kiểm lại payload/hash và quyền. |
| Đóng gói | Bổ sung lại `.env.example` sinh từ cấu hình và `.gitignore` đang thiếu trong ZIP đầu vào. |

## Kiến trúc và ranh giới

`Application.respond` → `PartnerBriefing` → Tool Harness → Gmail đọc → kiểm tra yêu cầu và danh tính → đọc chuỗi thư → thu thập nguồn và lịch → workflow chuyên biệt → báo cáo có cấu trúc → Evaluation Harness → trình bày trong chat.

Giữ các agent Email, Company Info, Web Research, Calendar, Report Generation, Memory và Human Approval của source. Các agent nghiên cứu chỉ có quyền đọc. Hai tool Gmail mới và tool lịch đều đi qua Tool Harness hiện có; luồng chat đánh giá chỉ mang capability `email:read` và `calendar:read` cho thao tác connector trực tiếp. Thu thập web tiếp tục đi qua scope `web:read` riêng. Sáu bước kiểm tra tool, audit, security và cơ chế phê duyệt không bị bypass.

Agent tạo bản nháp, nguồn và trace nội bộ để người dùng đọc/kiểm tra. Việc này khác với import báo cáo vào knowledge hoặc gửi ra ngoài; hai thao tác đó vẫn cần phê duyệt. Không có email hay sự kiện thật nào được tạo trong quá trình phát triển bản cập nhật.

Worker tự động vẫn có thể chạy bằng `python -m pu worker` và giữ cấu hình hiện có. AgentOps/Grafana có sẵn, chạy ở port 3000, tách Dashboard 9000:

```bash
docker compose -f observability/docker-compose.yml up -d
```

## Kiểm thử và giới hạn

Kết quả kiểm thử chi tiết nằm trong `docs/INVITATION_BRIEFING_TESTS.txt`. Có test tích hợp chạy `Application.respond` với provider và Gmail/web giả lập, bao gồm lời mời cũ, nhiều ứng viên, chọn công ty, lỗi Gmail, lỗi đọc chuỗi thư, danh tính không nhất quán, lịch theo ngày, độ dài cuộc họp, MIME HTML và không tạo write/proposal.

```bash
python -m pytest evals/deterministic -q
python scripts/generate_env_example.py --check
```

Đã kiểm thử logic offline, chưa chạy end-to-end với API key/Google OAuth thật của anh hoặc chấm LLM-as-Judge bằng model trả phí. Chất lượng diễn đạt và nghiên cứu còn phụ thuộc model, quyền truy cập và nguồn web. Đây là triển khai luồng trợ lý nghiên cứu trong PU, không phải bản sao toàn bộ năng lực của ChatGPT.

Giới hạn có chủ ý: tìm tối đa 50 email phù hợp mỗi lượt, đọc 30 tin mới nhất mỗi chuỗi; nội dung mỗi thư tối đa 32.000 ký tự, có cảnh báo nếu bị cắt. Kiểm tra lịch Google primary và lịch local; chưa đọc lịch rảnh của đối tác hoặc toàn bộ calendar phụ. Ngày/giờ phức tạp chưa phân giải được sẽ được ghi rõ, không bịa giờ trống. Không đọc attachment Gmail trong luồng mới. Nguồn công khai của công ty trùng tên cần khớp miền hoặc có liên kết nhận diện rõ; chưa dùng tên công ty đơn lẻ để nhập nhầm bằng chứng.


## Giao diện trò chuyện (bản cập nhật tiếp theo)

Mở mục **Trò chuyện** (`#chat`) sau khi khởi động lại dashboard. Không cần build frontend. Nếu trình duyệt vẫn hiện giao diện cũ, tải lại trang.

- Câu trả lời nằm trên nền thoáng, có tên PU, khoảng cách đoạn và danh sách rõ hơn; tin nhắn của anh giữ dạng bong bóng.
- Trích dẫn dạng `[1]` hoặc `[thư]` trở thành nhãn liên kết; mục **Nguồn tham khảo** mở danh sách các URL thực sự có trong câu trả lời. Không tự gán nhãn “đã xác minh” cho một liên kết.
- Lịch đề xuất hiển thị bảng ngày, khung giờ, thời lượng. Đây là thông tin để anh cân nhắc, không phải thao tác tạo sự kiện. Cửa sổ báo cáo tiếp tục kiểm tra độ mới của lịch.
- Ô nhập cố định cuối khung chat, hỗ trợ Enter để gửi, Shift+Enter xuống dòng và giữ thao tác nhập tiếng Việt bằng IME. Gợi ý ở màn hình đầu chỉ điền câu hỏi, anh có thể sửa trước khi gửi.
- Có lối mở lịch sử hội thoại, sao chép câu trả lời, đọc báo cáo đầy đủ và duyệt hành động đã được backend đề xuất. Nút duyệt chỉ xuất hiện khi báo cáo đạt phiên bản chính sách hiện tại (`company-boundary-v2`).
- CSS có bố cục màn hình nhỏ, chế độ sáng/tối và trạng thái focus bàn phím; các màn hình quản trị vẫn giữ nguyên.

Kiểm tra cập nhật: 55 kiểm thử JavaScript thành công (`node --test evals/deterministic/*.cjs`); 781 kiểm thử Python thành công, 13 bỏ qua có điều kiện. Bao gồm trích dẫn/URL, nội dung độc hại, lịch còn hiệu lực, streaming/dừng, lịch sử và phê duyệt. Chưa kiểm tra trực quan trên trình duyệt: môi trường không có Chromium, tải trình duyệt thử nghiệm thất bại. Chưa chạy với tài khoản Gmail/Calendar thật.
