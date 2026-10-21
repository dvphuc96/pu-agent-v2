# Phase 0 — Báo cáo baseline đa người dùng

Ngày chạy: 2026-10-21.  
Nhánh: `cursor/multi-user-phase0-baseline-b39a`.  
Phạm vi: đo hiện trạng và ghi nhận lỗ hổng. Không đổi hành vi sản phẩm.

Hợp đồng các phase nằm ở `docs/MULTI_USER_ARCHITECTURE_ROADMAP.md`.

Không có file `.env` và không có thư mục `.pu` trong checkout. Mọi test dùng thư mục tạm. Không có API key, token OAuth, hay dữ liệu người thật. Eval sống (`PU_RUN_LIVE_EVALS`) không được bật.

## 1. Suite hiện có

Lệnh, sau khi cài extra `dev`, `sources`, `pdf`, `gmail`, `gcal`:

```text
PU_HOME=/tmp/pu-phase0-isolated2 \
PU_API_KEY= ANTHROPIC_API_KEY= OPENAI_API_KEY= \
OTEL_EXPORTER_OTLP_ENDPOINT= \
python3 -m pytest -q evals/deterministic --tb=no
```

Python 3.12.3, pytest 9.1.1.

| Lần chạy | Kết quả | Thời gian |
| --- | --- | --- |
| Chỉ extra `dev` | 776 passed, 5 failed, 13 skipped | 13,57s |
| Thêm `sources`, `pdf`, `gmail`, `gcal` | **783 passed, 0 failed, 11 skipped** | 17,16s |

Năm failure của lần chỉ cài `dev` là thiếu gói tùy chọn, không phải lỗi logic:

- `test_partner_brief_relevance.py`: `ModuleNotFoundError: pypdf` (extra `sources`).
- `test_report_rendering.py::test_write_pdf_injects_unicode_font_face_into_source`: `xhtml2pdf` chưa có nên `CreatePDF` là `None` (extra `pdf`).

Mười một skip còn lại đều là eval sống trong `evals/deterministic/test_tool_trigger.py`, chờ `PU_RUN_LIVE_EVALS=1` và một API key. Chúng được bỏ qua có chủ đích.

Eval judge (`evals/judge`) không chạy vì chúng gọi model thật.

Sau khi thêm test tái hiện, suite đầy đủ được chạy lại. Kết quả nằm ở mục 8.

## 2. Phát hiện phân tích tĩnh

Test tái hiện: `evals/deterministic/test_phase0_multi_user_baseline.py`.  
Canary cố định, không phải khóa thật: `sk-phase0canarysecretxx`.  
Mỗi lỗi đã xác nhận là một test `xfail(strict=True)`. Chạy với `--runxfail` thì cả tám test fail đúng assertion mong đợi, không fail vì lỗi dựng fixture.

### 2.1 Redact trên SQLite nhưng không trên JSONL/OTel — đã xác nhận

`SQLiteAgentEventRepository.append` redact payload trước khi ghi `agent_events`. `AgentOpsHarness.publish` sau đó gọi `tracer.event` với payload gốc. `Tracer.event` ghi nguyên dict vào `traces/<ngày>.jsonl` và vào attribute span OTel.

Test `test_agentops_redacts_canary_before_jsonl_and_otel` công bố một sự kiện có canary. Kết quả đo được: SQLite không chứa canary; JSONL và OTel chứa. Danh sách rò là `['jsonl', 'otel']`.

Không xác nhận nhầm sang mọi file JSONL. `JsonlToolAuditSink` đã redact, và `evals/deterministic/test_phase5_tool_security_harness.py::test_jsonl_audit_redacts_secret_fields` đang khóa hành vi đó. Lỗ hổng là fan-out JSONL/OTel của tracer, không phải `traces/tool-audit.jsonl`.

Quan sát kèm, chỉ bằng đọc mã `SQLiteToolAuditSink.append`: `record_json` được redact, còn cột `result_summary`, `error` và `reason` ghi từ bản ghi gốc. Một bí mật nằm trong các cột đó sẽ còn trong SQLite dù JSON của cùng hàng đã sạch. Chưa có test tái hiện riêng.

### 2.2 `recover_inflight()` fail mọi approval `executing` — đã xác nhận

`SQLiteApprovalRepository.recover_inflight` chọn `status='executing'` và cập nhật cả tập đó thành `failed`, kèm câu "process restarted while action was executing". Không có tham số owner, không đọc `briefing_state.lease_owner` / `lease_until`.

Test `test_recover_inflight_preserves_other_owner_and_live_lease` tạo hai hàng `executing` (`user-a`, `user-b`), một hàng `pending`, và một lease còn hạn của worker khác. Hàng `pending` giữ nguyên. Hàng của `user-a` bị `failed` dù lease còn sống. Câu lệnh SQL cập nhật mọi hàng `executing`, nên hàng `user-b` cùng số phận. Hành vi fail-closed một process là có chủ đích trong docstring hiện tại; với hai owner và hai instance thì đó là lỗi so với MU-09.

### 2.3 Worker/collector đọc Gmail, Calendar, trang web ngoài Tool Harness — đã xác nhận

Đo bằng stub, không gọi mạng và không dùng token thật. File `gmail-token.json` trong test chỉ là `{}` để rẽ nhánh "đã kết nối".

| Đường | Kết quả đo | Test |
| --- | --- | --- |
| `BriefingService.cycle` gọi `pu.tools.gmail.sync` | bypass `gmail`, harness rỗng | `test_worker_gmail_read_goes_through_tool_harness` |
| `schedule_meeting_briefs` gọi `read_availability` | bypass `calendar` | `test_worker_calendar_read_goes_through_tool_harness` |
| `collect_partner_sources` khi `app` là `None` | `fetch_source` chạy ngoài harness (`page` và sau đó cả `calendar`) | `test_collector_page_read_without_app_goes_through_tool_harness` |
| `collect_partner_sources` khi có `app` | `read_web_page` đi qua harness; `requested_partner_availability` vẫn ngoài harness | `test_collector_calendar_read_goes_through_tool_harness` |

Điểm cần nói rõ: job worker có truyền `app` vào collector, nên lần đọc trang của đường đó đi qua Tool Harness. Phát hiện "page reads bypass" đúng với collector không có `app`, không đúng với đường job đã có `app`. Lịch vẫn ngoài harness ở cả hai đường.

Các callsite cùng loại, xác nhận bằng đọc mã, chưa có test riêng:

- `pu/ops/workspace_api.py`: op `fetch_source` gọi `fetch_source` trực tiếp.
- `pu/ops/dashboard.py`: `gmail_sync_action` gọi `gmail.sync` trực tiếp.
- `pu/graph/workflows/triage.py`: đọc `calendar.ics` trực tiếp từ đĩa.

### 2.4 `Tracer.__init__` xóa `_trace_api` sau khi OTel khởi tạo — đã xác nhận

`_init_otel` gán `self._trace_api = trace`. Ngay sau lời gọi đó, `__init__` gán `self._trace_api = None`. `event()` chỉ gọi `set_span_in_context` khi `_trace_api` khác `None`, nên span con không nhận parent của workflow.

Test `test_tracer_init_keeps_otel_trace_api` thay `_init_otel` bằng một hàm đặt sentinel rồi dựng `Tracer`. Sau `__init__`, `_otel_tracer` còn và `_trace_api` là `None`. Không cần gói exporter để chứng minh lệnh gán đè.

### 2.5 `list_events` biến lỗi Google thành "không có sự kiện" — đã xác nhận

`list_google_events` trả chuỗi bắt đầu bằng `Google Calendar unavailable (...)` khi API lỗi. `list_events` bỏ mọi chuỗi bắt đầu bằng `No Google` hoặc `Google Calendar unavailable`. Nếu lịch local trống, kết quả còn lại là:

```text
No events found between 2026-10-21 and 2026-10-21. Checked: Google Calendar, pu's local calendar.
```

Test `test_list_events_surfaces_google_error_instead_of_empty_diary` dùng stub, không gọi Google. Assertion thất bại đúng trên câu `No events found`.

Khi lịch local có sự kiện, lỗi Google cũng bị bỏ khỏi câu trả lời. `test_list_events_graceful_failure_of_one_source` đang khóa hành vi đó. Trường hợp lịch local trống mới là lỗi "biến thành không có sự kiện". Cả hai đều trái với hợp đồng trong `pu/agents/calendar.py`: một lần đọc thất bại không phải lịch trống.

### Tóm tắt

| Phát hiện | Kết luận |
| --- | --- |
| Redact SQLite, lọt JSONL/OTel | Đã xác nhận |
| `recover_inflight` bỏ qua owner và lease | Đã xác nhận |
| Worker/collector vòng qua Tool Harness | Đã xác nhận, với ngoại lệ đọc trang khi collector có `app` |
| `_trace_api` bị xóa sau OTel init | Đã xác nhận |
| Lỗi Google Calendar thành "No events found" | Đã xác nhận |

Không có phát hiện nào trong năm mục bị bác.

## 3. Giả định một người dùng

### 3.1 Principal cứng

Không có kiểu principal `USER` / `WORKER` / `PLATFORM_ADMIN`. Các chuỗi đang dùng:

- `local-user` tại runtime, app, collector, orchestration, scoped agent, và phần lớn test.
- `local-dashboard-user` khi dashboard phê duyệt.
- `graph-local-user` trong `pu/graph/nodes.py`.
- `automatic-briefing` là `decided_by` của approval do worker tạo.

`grep` trên `pu/` không thấy `user_id`, `owner_user_id`, `csrf`, `oidc`, `HttpOnly`, hay `SameSite`.

### 3.2 Trạng thái global trong process

- `pu/ops/browser_agent.py`: một `_agent`, một `_dashboard_session`, một `agent_lock`. Comment trong file nói đây là đúng cho công cụ local một người vì mọi thread chia sẻ một connection SQLite.
- `pu/ops/briefing.py`: `_services` ánh xạ một home sang một `BriefingService`.
- `pu/ops/chat_runs.py`: `_runs` là dict hủy chat của cả process.
- `pu/ops/workspace_api.py`: `_model_limit` là rate limit trong bộ nhớ của cả process.
- Rate limit tool (`InMemoryRateLimiter`) sống theo object harness. Dashboard chỉ dựng một application, nên hạn mức là của cả process, không phải của từng user.
- `get_agent()` dựng application một lần từ `load_settings()` và giữ đến khi `rebuild()`.

### 3.3 Một database, hai kiểu connection

- `pu/db.py` `connect()` giữ connection dài cho memory và session. Dashboard mở connection này với `check_same_thread=False` và dùng chung giữa các thread.
- `SQLiteDatabase.connection()` mở connection ngắn cho workflow, approval, event, audit.
- Cả hai cùng trỏ tới một file `PU_HOME/state.db`. Không có tên schema theo user.
- `recover_inflight()` chạy mỗi lần `build_dependencies()`, tức là mỗi lần tạo application. Process thứ hai mở cùng file sẽ fail mọi approval đang `executing`.

### 3.4 Credential từ môi trường và `.pu`

- `pu/config.py` đọc `.env` lúc import (`find_dotenv(usecwd=True)`) và lấy `PU_API_KEY`, `PU_HOME`, cùng các biến nhà cung cấp.
- `pu/ops/settings_api.py` ghi ngược vào file env.
- Token và secret trên đĩa, một bộ cho cả home, liệt kê trong `pu/ops/reset.py`: `credentials.json`, `gmail-token.json`, `gmail-send-token.json`, `calendar-token.json`, `google-token.json`, `google-calendar-token.json`, `drive-token.json`, và `token.json` do tool lịch dùng.
- Không mã hóa token. Khóa mã hóa không tồn tại, nên cũng không nằm ngoài DB.

### 3.5 Dữ liệu không có chủ

Mọi hàng dưới đây thiếu `owner_user_id`. Danh sách cột cần thêm nằm ở mục 5.

Workspace id do client gửi (`workspace_action`, các route dashboard) được tin vì chỉ có một người. Đó là điểm MU-12.

Dashboard lắng nghe `127.0.0.1`. Không có xác thực trên port local: process khác trên cùng máy gọi được API. Chưa phải CSRF từ trình duyệt trên internet, nhưng mô hình web nhiều user không được giữ giả định này.

## 4. Mô hình đe dọa

### 4.1 Tài sản

Báo cáo, nguồn nghiên cứu, email CRM, lịch, fact, episode, hội thoại, attachment, artifact, đề xuất phê duyệt, token OAuth, API key model, trace và usage.

### 4.2 Chủ thể

Như ADR-MU-001: `USER`, `WORKER` ủy quyền theo job, `PLATFORM_ADMIN` không đọc dữ liệu riêng theo mặc định. Kẻ tấn công trong mô hình này là user khác đã đăng nhập, một worker bị lệch lease, hoặc một request giả mạo cookie.

### 4.3 Biên tin cậy

1. Trình duyệt → cookie phiên và CSRF.
2. Phiên → principal.
3. Principal + operation + scope + owner + approval → Tool Harness.
4. Tool Harness → nhà cung cấp và đĩa.
5. Mọi nhánh ghi log → redact → JSONL, OTel, SQLite, metrics.
6. PostgreSQL role ứng dụng → RLS, không `BYPASSRLS`.

Hôm nay các biên 1, 5 và 6 chưa có. Biên 3 tồn tại cho agent loop nhưng worker/collector đục lỗ.

### 4.4 Đe dọa và cổng tương ứng

| Đe dọa | Hiện trạng | Cổng |
| --- | --- | --- |
| IDOR: biết report id hoặc workflow id là đọc được | Mọi repository lấy theo id, không theo owner | MU-01, MU-11 |
| Tải artifact của người khác | `reports/` và outbox là file trong một home | MU-02 |
| Dùng connection id của người khác | Token là file chung, không gắn user | MU-03 |
| Phê duyệt hộ | `approve` nhận id, `decided_by` là chuỗi local | MU-04 |
| Job song song trộn dữ liệu | Một DB, một agent, rate limit process | MU-05 |
| Phiên hoặc token đã thu hồi vẫn dùng được | Không có phiên để thu hồi | MU-06 |
| Đọc hàng người khác qua SQL | Không RLS | MU-07 |
| Bí mật rơi vào telemetry | Đã đo trên JSONL và OTel | MU-08 |
| Instance kia khởi động làm hỏng hoặc gửi trùng side effect | `recover_inflight` fail mọi `executing`; side effect không có lease | MU-09 |
| Import gán nhầm dữ liệu cũ cho user mới | Không có bản đồ `local-user` | MU-10 |
| CSRF khi có cookie phiên | Chưa có CSRF; hôm nay chỉ bind loopback | MU-11 |
| Client tự khai owner | Body `workspace_id` được tin | MU-12 |
| Worker giữ quyền sau khi job xong | Không có ủy quyền theo job | P3-04 |
| Admin xem nội dung riêng qua metrics hoặc trace | Trace là file chung; metrics chưa lọc payload | OPS-04, OPS-06 |

### 4.5 Điều cố ý không coi là đe dọa của đợt này

Chia sẻ có chủ đích, tổ chức, và vai trò trong workspace. Chúng nằm ngoài ADR-MU-001.

## 5. Tài nguyên cần `owner_user_id`

Cột `owner_user_id` đứng trên bảng cha. Bảng con dùng khóa ngoại kép với cha, ví dụ `(workflow_run_id, owner_user_id)`, và vẫn mang `owner_user_id` để RLS không phải join mới lọc được.

### 5.1 Bảng SQLite hiện có

| Bảng | Vì sao là dữ liệu riêng |
| --- | --- |
| `calendar_events` | Lịch người dùng tạo |
| `facts` | Bộ nhớ dài hạn |
| `episodes` | Tóm tắt việc đã xảy ra |
| `chat_log` | Hội thoại |
| `crm_emails` | Hộp thư |
| `knowledge_sources` | Tài liệu người dùng đưa vào |
| `knowledge_chunks` | Nội dung của các nguồn đó |
| `proposed_actions` | Hành động chờ duyệt và kết quả thực thi |
| `workflow_runs` | Một lần chạy agent |
| `workflow_stage_checkpoints` | Kết quả trung gian |
| `agent_events` | Telemetry có payload |
| `tool_audit_events` | Đối số và kết quả tool |
| `research_workspaces` | Hồ sơ công ty |
| `workspace_sources` | Bằng chứng đã thu |
| `workspace_reports` | Báo cáo |
| `workspace_messages` | Hỏi đáp trên nguồn |
| `workspace_deliveries` | Nơi đã gửi báo cáo |
| `briefing_state` | Cấu hình worker, người nhận, lease |
| `briefing_seen` | Email đã xử lý |
| `briefing_jobs` | Hàng đợi nghiên cứu |

### 5.2 File dưới home

Các file này cần một gốc lưu theo `owner_user_id`, không còn một thư mục `.pu` chung:

- `reports/*` (json, md, html, pdf)
- `traces/*.jsonl`, `traces/tool-audit.jsonl`
- `usage.jsonl`, `eval_runs.jsonl`
- `outbox/*`
- `calendar.ics`
- `SOUL.md`
- thư mục knowledge và skill cài trong home
- toàn bộ token và `credentials.json` đã liệt kê ở mục 3.4

Token là dữ liệu riêng và phải mã hóa bằng khóa ngoài DB. Chúng không được nằm trong bảng telemetry.

## 6. Ước lượng khối lượng Phase 1–6

Đây là kích thước kỹ thuật tương đối, theo bề mặt sửa và rủi ro. Không phải lịch ngày.

| Phase | Mức | Việc lớn nhất | Rủi ro nếu làm nông |
| --- | --- | --- | --- |
| 1 | Rất lớn | Đổi gốc sở hữu của mọi bảng và file; PostgreSQL + RLS + khóa ngoại kép; chặn IDOR và owner do client gửi; import có bản đồ | Một bảng sót cột là một lỗ MU-07 |
| 2 | Lớn | OIDC, cookie, CSRF, mã hóa token, bịt bypass harness, recovery theo lease, redact mọi sink | Sửa session trước khi có owner sẽ phát hành lỗ IDOR có đăng nhập |
| 3 | Trung bình | Hợp đồng request có kiểu và một state machine workflow | Hai đường workflow tiếp tục lệch trạng thái khi resume |
| 4 | Lớn | Attachment, công ty, lịch, memory, sáu AE với fixture A/B | Trùng tên công ty làm gộp dữ liệu hai user |
| 5 | Trung bình | Cây span, chi phí theo owner, eval tách home | Sửa OTel mà quên JSONL thì MU-08 vẫn đỏ |
| 6 | Trung bình, nhưng là cổng chặn | Chạy lại MU-01..12 trên PostgreSQL và hai instance | Xanh từng phase trên SQLite một process không chứng minh production |

Phase 1 và Phase 2 là phần lớn của rủi ro. Phase 4 rộng vì đụng nhiều agent nhưng đi trên ranh giới đã có ở Phase 1–3. Phase 6 không thêm năng lực; nó chỉ có giá trị nếu mười hai MU chạy cùng một cấu hình production.

## 7. Việc cố ý chưa làm

- Không sửa năm lỗi đã xác nhận. Test để `xfail` đến phase sở hữu chúng.
- Không tạo issue GitHub. Bản dán nằm ở `docs/ROADMAP_ISSUES.md`.
- Không chạy eval judge và không chạy eval sống.

## 8. Suite sau khi thêm test tái hiện

Lệnh cách ly giống mục 1, gồm file mới:

```text
783 passed, 11 skipped, 8 xfailed in 16.61s
```

Tám `xfailed` là đúng tám test trong `test_phase0_multi_user_baseline.py`. Không có failure mới. Các test cũ không bị sửa.
