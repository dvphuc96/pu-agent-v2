# Issue lộ trình đa người dùng

Môi trường agent này chỉ được dùng GitHub CLI để đọc. `gh issue list` trên `dvphuc96/pu-agent-v2` trả về danh sách rỗng và lệnh tạo issue không được phép. Bảy issue dưới đây là bản đầy đủ để dán lên repository đó, một issue cho mỗi phase 0..6.

Nhãn gợi ý nằm trong từng issue. Không tạo nhãn tự động.

---

## Phase 0

**Title:** Phase 0 — Baseline và mô hình đe dọa đa người dùng

**Labels:** `phase-0`, `multi-user`, `docs`

**Body:**

### Bối cảnh

ADR-MU-001 chọn mô hình A: tài khoản cá nhân độc lập, `user_id` UUID do backend cấp, một workspace mỗi người, không chia sẻ. Hợp đồng đầy đủ nằm ở `docs/MULTI_USER_ARCHITECTURE_ROADMAP.md`.

Phase này chỉ đo hiện trạng. Không đổi hành vi sản phẩm.

### Phạm vi

- Chạy `evals/deterministic` trong môi trường tách biệt, ghi pass/fail.
- Thêm test tái hiện, `xfail` kèm lý do khi đúng là lỗi, cho các phát hiện phân tích tĩnh đã được kiểm chứng.
- Kiểm kê giả định một người dùng.
- Viết mô hình đe dọa và danh sách tài nguyên cần `owner_user_id`.
- Ước lượng khối lượng kỹ thuật Phase 1–6, không dùng lịch ngày.
- Báo cáo tại `docs/phase0/BASELINE_REPORT.md`.
- Không dùng dữ liệu hoặc credential người thật.

### Ngoài phạm vi

Schema, PostgreSQL, OIDC, RLS, sửa các lỗi vừa tái hiện.

### Phụ thuộc

Không.

### Cổng

- Báo cáo baseline đã có mặt và mỗi phát hiện được đánh dấu đã xác nhận hoặc chưa xác nhận.
- Suite deterministic hiện có vẫn pass khi cài đủ extra `dev`, `sources`, `pdf`, `gmail`, `gcal`.
- Test mới nằm ở `evals/deterministic/test_phase0_multi_user_baseline.py` và là `xfail` strict cho đúng lỗi đã xác nhận.

### Việc xong khi

PR tài liệu và test tái hiện được mở, tham chiếu issue này. Runtime không đổi.

---

## Phase 1

**Title:** Phase 1 — Danh tính, ownership và PostgreSQL

**Labels:** `phase-1`, `multi-user`, `security`

**Body:**

### Bối cảnh

Hiện không có `user_id`, không có `owner_user_id`, và mọi bảng SQLite là dữ liệu của một `local-user`. Chi tiết ở `docs/phase0/BASELINE_REPORT.md`.

### Phạm vi

- Backend cấp `user_id` UUID. Mỗi user có đúng một workspace cá nhân.
- Thêm `owner_user_id` cho mọi bảng và tệp riêng tư đã liệt kê ở Phase 0.
- Khóa ngoại kép `(workflow_run_id, owner_user_id)` và các cặp tương đương cho checkpoint, event, audit, nguồn, báo cáo.
- PostgreSQL cho production. SQLite dev/test đi cùng ranh giới sở hữu, không phải một schema "không owner".
- RLS bật và `FORCE RLS`. Role ứng dụng không có `BYPASSRLS`.
- Mọi trường owner hoặc workspace do client gửi đều bị bỏ qua; server lấy owner từ principal đã xác thực.
- Nhập dữ liệu cũ gắn `local-user` chỉ khi có bản đồ tường minh sang `user_id`. Thiếu bản đồ thì từ chối cả lô.

### Phụ thuộc

- Phase 0 đã khóa danh sách tài nguyên và mô hình đe dọa.

### Cổng

- MU-01: A đọc báo cáo hoặc workflow của B bằng ID thì bị từ chối.
- MU-02: A tải artifact của B thì bị từ chối.
- MU-07: với RLS, truy vấn của A không thấy hàng của B.
- MU-10: import `local-user` không có bản đồ thì thất bại; có bản đồ thì hàng thuộc đúng user.
- MU-11: đổi ID trên URL hoặc body không đọc được tài nguyên của người khác.
- MU-12: body chứa `owner_user_id` hoặc `workspace_id` của B vẫn ghi và đọc theo principal A.

CSRF của cookie phiên thuộc Phase 2. Phase 1 vẫn phải chặn IDOR khi đã biết principal.

### Việc xong khi

Toàn bộ cổng trên pass bằng fixture A/B, không dùng dữ liệu người thật. Chưa cần OIDC nếu test gắn principal bằng seam nội bộ đã được ghi trong ADR; seam đó phải bị thay bởi phiên thật trước Phase 6.

---

## Phase 2

**Title:** Phase 2 — Bảo mật phiên và toàn vẹn thực thi

**Labels:** `phase-2`, `multi-user`, `security`

**Body:**

### Bối cảnh

Dashboard hiện bind `127.0.0.1`, không có phiên, không CSRF, không mã hóa token. Worker gọi Gmail và Calendar ngoài Tool Harness. `recover_inflight()` đánh `failed` mọi hàng `executing`. Canary lọt JSONL và OTel. Xem các test `xfail` trong `evals/deterministic/test_phase0_multi_user_baseline.py`.

### Phạm vi

- OIDC Authorization Code + PKCE.
- Cookie phiên `HttpOnly`, `Secure`, `SameSite`, cộng CSRF cho mọi yêu cầu đổi trạng thái.
- Thu hồi phiên và token chặn ngay thao tác sau đó.
- Token OAuth mã hóa; khóa không nằm trong DB và không nằm trong telemetry.
- Đọc Gmail, Calendar và trang web của worker/collector đi qua Tool Harness với principal `WORKER` và `owner_user_id` của job.
- Phục hồi có lease: không fail hàng `executing` của owner khác; không fail hàng mà instance khác còn giữ lease; không thực thi lại side effect đã có thể gửi.
- Redact trước khi ghi JSONL, OTel, cột `tool_audit_events`, và mọi sink khác.

### Phụ thuộc

- Phase 1: `owner_user_id`, RLS, và từ chối owner do client gửi.

### Cổng

- MU-03: A dùng connection ID của B thì không có cuộc gọi nhà cung cấp.
- MU-04: A phê duyệt hành động của B thì bị từ chối, kể cả khi biết `approval_id`.
- MU-05: job A và B đồng thời không trộn email, lịch, báo cáo, hay audit.
- MU-06: sau khi thu hồi phiên hoặc token, request tiếp theo bị chặn.
- MU-08: canary vắng mặt ở SQLite, JSONL, OTel, cột audit và usage ledger.
- MU-09: instance thứ hai khởi động không làm `failed` thực thi đang sống và không gửi trùng.

### Việc xong khi

Các `xfail` Phase 0 về redact, `recover_inflight`, và bypass Tool Harness được gỡ vì hành vi đúng đã pass. Không còn đường `gmail.sync`, `read_availability`, `fetch_source` từ worker/collector ngoài harness.

---

## Phase 3

**Title:** Phase 3 — Hợp đồng agent có kiểu và trạng thái workflow thống nhất

**Labels:** `phase-3`, `multi-user`

**Body:**

### Bối cảnh

Principal đang là chuỗi cứng `local-user`, `local-dashboard-user`, `graph-local-user`. Workflow, checkpoint và sự kiện chưa khóa theo owner. Worker giữ trạng thái process-global.

### Phạm vi

- Hợp đồng request có kiểu: principal, `owner_user_id`, workspace, scope agent/tool, trạng thái phê duyệt.
- Một hàng trạng thái cho mỗi workflow run. Resume không tạo run mới và không chạy lại stage đã xong của đúng owner.
- Checkpoint, stage, event dùng khóa `(workflow_run_id, owner_user_id)`.
- `WORKER` chỉ giữ ngữ cảnh owner trong đời sống của job.

### Phụ thuộc

- Phase 2: Tool Harness đã nhận principal và owner; lease đã có chủ.

### Cổng

- P3-01: request thiếu principal hoặc owner bị từ chối trước khi gọi model hoặc tool.
- P3-02: resume một workflow đang dở tạo đúng một run, không nhân đôi stage đã hoàn thành.
- P3-03: checkpoint của A không đọc được bằng workflow id của B.
- P3-04: khi job kết thúc hoặc lease hết hạn, worker không còn đọc được dữ liệu của owner đó.

### Việc xong khi

Bốn cổng trên pass. Không còn default `local-user` trên đường production.

---

## Phase 4

**Title:** Phase 4 — Agent nghiệp vụ và fixture hai người dùng

**Labels:** `phase-4`, `multi-user`

**Body:**

### Bối cảnh

Attachment, hồ sơ công ty, lịch và bộ nhớ đều nằm trong một SQLite và một thư mục home. `list_events` biến lỗi Google Calendar thành `No events found` khi lịch local trống. Hợp đồng agent lịch đã nói một lần đọc thất bại không phải lịch trống.

### Phạm vi

- Attachment theo owner.
- Nghiên cứu công ty và báo cáo theo workspace của đúng user.
- Lịch: lỗi nguồn thành trạng thái không khả dụng; không suy ra lịch trống.
- Memory và knowledge theo owner.
- Fixture A/B dùng cho mọi cổng AE. Trùng tên công ty không được gộp dữ liệu.

### Phụ thuộc

- Phase 3: workflow và agent request đã mang owner.

### Cổng

- AE-01: A không đọc hoặc tải attachment của B.
- AE-02: workspace công ty của A không lộ email, nguồn, báo cáo của B dù cùng tên công ty.
- AE-03: lỗi Google Calendar trả trạng thái không khả dụng, không trả "không có sự kiện"; không đọc lịch của user kia.
- AE-04: tìm memory và knowledge của A không trả fact hoặc chunk của B.
- AE-05: cùng một yêu cầu nghiên cứu trên hai user tạo hai báo cáo và hai content hash.
- AE-06: agent từ chối connection id, thread id, report id, workspace id của người kia trước cuộc gọi nhà cung cấp.

### Việc xong khi

Sáu AE pass với fixture hai user. `xfail` của `list_events` ở Phase 0 được gỡ.

---

## Phase 5

**Title:** Phase 5 — Eval và AgentOps

**Labels:** `phase-5`, `multi-user`, `agentops`

**Body:**

### Bối cảnh

`Tracer.__init__` gán `_trace_api = None` sau `_init_otel`, nên span con không nhận parent context. `AgentOpsHarness` redact khi ghi `agent_events` nhưng ghi payload gốc vào JSONL và attribute OTel. Usage ledger chưa có owner.

### Phạm vi

- Sửa cây span OTel.
- Gắn chi phí token với `owner_user_id`.
- Eval và trace tách theo user.
- Metrics không chứa nội dung riêng tư.

### Phụ thuộc

- Phase 2: redact trên mọi sink.
- Phase 4: fixture A/B để kiểm tra cách ly trace và chi phí.

### Cổng

- OPS-01: span con nằm dưới span workflow; `_trace_api` còn sau khi OTel khởi tạo.
- OPS-02: canary vắng mặt ở JSONL, OTel, SQLite, cột audit và usage (cùng MU-08).
- OPS-03: mỗi lần gọi LLM ghi token và chi phí theo `owner_user_id`.
- OPS-04: A không đọc trace của B. Admin chỉ thấy số tổng hợp.
- OPS-05: eval hai user không dùng chung home, database, hay file trace.
- OPS-06: `/metrics` và text Prometheus không nhúng prompt, email, hay báo cáo.

### Việc xong khi

Sáu OPS pass. `xfail` của `_trace_api` và phần OTel/JSONL của test redact được gỡ.

---

## Phase 6

**Title:** Phase 6 — Sẵn sàng production đa người dùng

**Labels:** `phase-6`, `multi-user`, `release`

**Body:**

### Bối cảnh

Các phase trước mỗi phase giữ một lát cổng. Phase này chạy lại toàn bộ trên cấu hình production: PostgreSQL, RLS buộc, hai instance, OIDC thật hoặc seam đã được thay bằng phiên thật, fixture A/B.

### Phạm vi

- Cổng phát hành MU-01..MU-12.
- Xác nhận role ứng dụng không có `BYPASSRLS`.
- Xác nhận khóa mã hóa token không nằm trong DB và không nằm trong repo.
- Xác nhận import `local-user` vẫn từ chối khi thiếu bản đồ.
- Xác nhận không còn đường worker/collector ngoài Tool Harness.
- Gỡ mọi `xfail` Phase 0 mà phase sau đã nhận sửa. `xfail` còn lại chỉ được tồn tại nếu kèm issue mở và không thuộc cổng phát hành.

### Phụ thuộc

- Phase 1, 2, 3, 4 và 5 đã xanh cổng của chúng.

### Cổng

Tất cả MU-01, MU-02, MU-03, MU-04, MU-05, MU-06, MU-07, MU-08, MU-09, MU-10, MU-11, MU-12 pass trên cùng một lần chạy phát hành.

### Việc xong khi

Biên bản cổng phát hành ghi đủ mười hai MU pass. Không phát hành nếu còn canary trong sink, còn IDOR, hoặc còn instance thứ hai làm fail thực thi đang sống.
