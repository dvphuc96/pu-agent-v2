# Lộ trình kiến trúc đa người dùng

Tài liệu này khóa quyết định biến PU-Agent từ công cụ local một người dùng thành ứng dụng web nhiều tài khoản cá nhân độc lập. Đây là hợp đồng cho Phase 0 đến Phase 6. Phase 0 chỉ ghi nhận hiện trạng và mô hình đe dọa; không đổi hành vi sản phẩm.

Mô hình được chọn là **ADR-MU-001, mô hình A**.

## 1. Quyết định đã khóa

### 1.1 Ranh giới sản phẩm

- Mỗi người có một tài khoản cá nhân. Không có chia sẻ, nhóm, tổ chức, hay workspace dùng chung.
- Mỗi người có đúng một workspace cá nhân.
- Gốc sở hữu là `user_id` kiểu UUID do backend cấp. Client không được chọn, gửi kèm, hoặc ghi đè giá trị này.
- Mọi hàng và tệp riêng tư đều gắn với đúng một `owner_user_id`.

### 1.2 Danh tính và phiên

- Đăng nhập bằng OIDC, luồng Authorization Code kèm PKCE.
- Sau khi đăng nhập, ứng dụng phát hành phiên của chính nó: cookie `HttpOnly`, `Secure`, `SameSite=Lax`.
- `Lax` được chọn vì callback OIDC là điều hướng GET cấp cao nhất từ nhà cung cấp danh tính. `Lax` vẫn gửi cookie trên điều hướng đó, nên cookie `state` và PKCE verifier còn sau vòng redirect. `SameSite=Strict` bỏ cookie trên điều hướng cross-site này và làm gãy Authorization Code + PKCE. `Lax` không gửi cookie cho POST hay subresource cross-site. Mọi yêu cầu đổi trạng thái vẫn cần CSRF token gắn với phiên; `Lax` không thay token đó.
- Thu hồi phiên hoặc token phải chặn thao tác tiếp theo (MU-06).

### 1.3 Ủy quyền

Một thao tác chỉ được phép khi đồng thời đủ:

1. Chủ thể đã xác thực.
2. Đúng loại thao tác.
3. Đúng scope của agent và tool.
4. Chủ sở hữu tài nguyên khớp với ngữ cảnh được phép.
5. Trạng thái phê duyệt còn hiệu lực, nếu thao tác có tác dụng phụ.

Ba loại chủ thể:

| Chủ thể | Ý nghĩa | Dữ liệu riêng |
| --- | --- | --- |
| `USER` | Người đã đăng nhập | Chỉ dữ liệu của chính họ |
| `WORKER` | Tiến trình nền, nhận ủy quyền theo từng job | Chỉ `owner_user_id` của job đó, và chỉ trong thời hạn lease |
| `PLATFORM_ADMIN` | Vận hành nền tảng | Không đọc dữ liệu riêng theo mặc định |

`WORKER` không có danh tính sở hữu riêng. Ngữ cảnh chủ sở hữu được giao theo job và hết hiệu lực khi job kết thúc hoặc lease hết hạn.

### 1.6 Seam principal nội bộ của Phase 1

Tên: `InternalPrincipalSeam`, module `pu.identity.seam`.

Điểm gắn: trường `principal_seam` trên `ApplicationDependencies`, object do `create_application` và `build_dependencies` trả về. Seam đứng trước Tool Harness, approval và mọi repository khi chúng hỏi principal hiện tại. Fixture Phase 1 gọi `principal_seam.attach(principal)`. Seam trả principal vừa gắn. Seam không đọc `owner_user_id` hay `workspace_id` từ body.

Gỡ ở Phase 6: xóa module `pu.identity.seam` và trường `principal_seam`. Principal cùng `owner_user_id` chỉ còn đến từ phiên OIDC đã xác thực. Cổng phát hành đỏ nếu module còn import được, hoặc nếu request không có cookie phiên vẫn nhận một principal. Đây là seam được nêu ở mục "Việc xong khi" của issue Phase 1.

### 1.4 Dữ liệu production

- Production dùng PostgreSQL.
- Mọi bảng riêng tư có `owner_user_id`.
- Khóa ngoại xuyên thực thể dùng cặp cột, ví dụ `(workflow_run_id, owner_user_id)`, để một hàng con không thể trỏ sang workflow của người khác.
- Bật Row Level Security và `FORCE RLS`.
- Role ứng dụng không có `BYPASSRLS`.
- Token OAuth của nhà cung cấp được mã hóa; khóa mã hóa nằm ngoài cơ sở dữ liệu.
- Mọi sink telemetry đều redact trước khi ghi.
- Phục hồi job phải nhận biết lease: instance thứ hai không được đánh rơi thực thi đang sống và không được gửi trùng.

### 1.5 Ngoài phạm vi

Không làm chia sẻ báo cáo, mời thành viên, tổ chức, vai trò tùy biến trong workspace, hay đăng nhập bằng mật khẩu tự quản. Những thứ đó cần một ADR khác.

## 2. Bài kiểm cổng MU

Các bài này là cổng phát hành. Chúng dùng hai tài khoản cố định A và B, không dùng dữ liệu người thật.

| Mã | Kỳ vọng |
| --- | --- |
| MU-01 | A đọc báo cáo hoặc workflow của B bằng ID thì bị từ chối |
| MU-02 | A tải artifact của B thì bị từ chối |
| MU-03 | A đưa connection ID của B thì không có cuộc gọi nhà cung cấp |
| MU-04 | A phê duyệt hành động của B thì bị từ chối |
| MU-05 | Job của A và B chạy đồng thời không trộn dữ liệu |
| MU-06 | Phiên hoặc token đã thu hồi thì bị chặn |
| MU-07 | RLS che mọi hàng của B khỏi A |
| MU-08 | Bí mật canary không xuất hiện ở bất kỳ sink nào |
| MU-09 | Instance thứ hai khởi động lại không làm hỏng thực thi đang sống và không gửi trùng |
| MU-10 | Nhập dữ liệu `local-user` cũ bắt buộc có ánh xạ tường minh |
| MU-11 | IDOR và CSRF bị từ chối |
| MU-12 | `owner` hoặc `workspace` do client gửi lên bị bỏ qua |

## 3. Các phase

Phụ thuộc chạy một chiều: phase sau không bắt đầu phần cổng của mình khi cổng của phase trước còn đỏ. Tài liệu và test tái hiện của phase trước được phép đi song song với thiết kế.

### Phase 0 — Baseline và mô hình đe dọa

- **Phụ thuộc:** không.
- **Phạm vi:** chạy suite hiện có trong môi trường tách biệt; viết test tái hiện các lỗ hổng đã thấy bằng phân tích tĩnh; kiểm kê giả định một người dùng; viết mô hình đe dọa và danh sách tài nguyên cần `owner_user_id`; ước lượng khối lượng Phase 1–6.
- **Không làm:** đổi hành vi runtime, schema, hay API.
- **Cổng:** báo cáo `docs/phase0/BASELINE_REPORT.md` và suite deterministic vẫn xanh, trừ các test tái hiện được đánh dấu `xfail` có lý do.
- **Bằng chứng hiện trạng:** `evals/deterministic/test_phase0_multi_user_baseline.py`.

### Phase 1 — Danh tính, sở hữu, PostgreSQL

- **Phụ thuộc:** Phase 0 đã khóa mô hình đe dọa và danh sách bảng.
- **Phạm vi:**
  - Cấp `user_id` UUID ở backend và một workspace cá nhân cho mỗi user.
  - Thêm `owner_user_id` cho bảng riêng tư và khóa ngoại kép.
  - Đưa operational store production sang PostgreSQL; SQLite chỉ còn adapter dev/test có cùng ranh giới sở hữu.
  - Bật RLS + `FORCE RLS`, role ứng dụng không `BYPASSRLS`.
  - Bỏ qua mọi `owner_user_id` / `workspace_id` do client gửi.
  - Nhập dữ liệu `local-user` chỉ khi có bản đồ nguồn → `user_id` được xác nhận. Không có bản đồ thì từ chối, không gán vào user ngẫu nhiên.
  - Test gắn principal bằng `InternalPrincipalSeam` (mục 1.6), chưa cần OIDC.
- **Cổng:** MU-01, MU-02, MU-07, MU-10, phần IDOR của MU-11, MU-12.
  - MU-10 đi cùng phase này vì nó là cổng của bước nhập danh tính. Danh sách cổng ban đầu nêu MU-01, MU-02, MU-07, MU-11, MU-12; MU-10 là cổng kèm theo của cùng lát cắt sở hữu.
  - Phần IDOR của MU-11 ở phase này: đổi ID trên URL hoặc body không đọc được tài nguyên của người khác khi principal đã biết qua seam.
  - Phần CSRF của MU-11 không thuộc cổng Phase 1. Cổng đó nằm ở Phase 2, vì cookie phiên chưa tồn tại ở phase này.

### Phase 2 — Bảo mật phiên và toàn vẹn thực thi

- **Phụ thuộc:** Phase 1 đã có `owner_user_id` và RLS. Không xây session trên schema chưa có chủ sở hữu.
- **Phạm vi:**
  - OIDC Authorization Code + PKCE.
  - Cookie phiên `HttpOnly` + `Secure` + `SameSite=Lax`, kèm CSRF token cho mọi yêu cầu đổi trạng thái.
  - Thu hồi phiên và token có hiệu lực ngay.
  - Mã hóa token OAuth, khóa nằm ngoài DB.
  - Mọi đọc Gmail, Calendar và trang web đi qua Tool Harness, kèm principal và owner của job. Ngoài worker/collector, cổng này gồm đúng ba callsite:
    - `pu/ops/workspace_api.py` dòng 160–163, op `fetch_source`.
    - `pu/ops/dashboard.py` dòng 822–823, `gmail.sync` trong `gmail_sync_action`.
    - `pu/graph/workflows/triage.py` dòng 74–78, `todays_events` đọc `calendar.ics`.
  - `recover_inflight()` chỉ fail-closed hàng `executing` không còn lease sống và thuộc đúng owner của process đang phục hồi. Không đụng hàng của owner khác, không đụng thực thi mà instance khác còn giữ lease.
  - Redact JSONL trace và các cột `tool_audit_events.reason`, `result_summary`, `error`. Attribute OTel thuộc Phase 5, không thuộc cổng redact của phase này.
- **Cổng:** MU-03, MU-04, MU-05, MU-06, MU-08 cho JSONL và cột audit, MU-09, và phần CSRF của MU-11.
  - Phần CSRF của MU-11: request đổi trạng thái thiếu CSRF token, hoặc token không khớp phiên, bị từ chối. `SameSite=Lax` không tính là đạt cổng này.
- **Gỡ `xfail`, mỗi marker một lần, chỉ ở phase này:**
  - `test_agentops_redacts_canary_in_jsonl`
  - `test_sqlite_tool_audit_columns_redact_canary`
  - `test_recover_inflight_preserves_other_owner_and_live_lease`
  - `test_worker_gmail_read_goes_through_tool_harness`
  - `test_worker_calendar_read_goes_through_tool_harness`
  - `test_collector_page_read_without_app_goes_through_tool_harness`
  - `test_collector_calendar_read_goes_through_tool_harness`
  - `test_workspace_fetch_source_goes_through_tool_harness`
  - `test_dashboard_gmail_sync_goes_through_tool_harness`
  - `test_triage_ics_read_goes_through_tool_harness`
  - Không gỡ `test_agentops_redacts_canary_in_otel` và `test_tracer_init_keeps_otel_trace_api`. Hai marker đó thuộc Phase 5.

### Phase 3 — Hợp đồng agent có kiểu và trạng thái workflow thống nhất

- **Phụ thuộc:** Phase 2 đã gắn principal, scope và owner vào đường thực thi tool.
- **Phạm vi:**
  - Mỗi yêu cầu agent mang kiểu rõ: principal, `owner_user_id`, scope, workspace, và trạng thái phê duyệt.
  - Một bản ghi workflow cho mỗi lần chạy. Graph workflow và research workflow không còn hai trạng thái lệch nhau.
  - Checkpoint, stage và sự kiện cùng khóa `(workflow_run_id, owner_user_id)`.
  - Worker chỉ nhận ngữ cảnh ủy quyền theo job, không đọc trạng thái global của process.
- **Cổng đề xuất cho phase này:**
  - P3-01: request thiếu principal hoặc owner bị từ chối ở biên runtime.
  - P3-02: một workflow chỉ có một hàng trạng thái, resume không tạo run thứ hai.
  - P3-03: checkpoint của A không đọc được bằng workflow id của B.
  - P3-04: worker hết job thì mất ngữ cảnh owner, kể cả khi process còn sống.

### Phase 4 — Agent nghiệp vụ

- **Phụ thuộc:** Phase 3 đã có hợp đồng principal/owner trên workflow.
- **Phạm vi:** attachment, hồ sơ công ty, semantics lịch khi nguồn lỗi, và bộ nhớ. Fixture hai người dùng cho toàn bộ AE.
- **Cổng AE, fixture A/B:**
  - AE-01: attachment của A không đọc hoặc tải được bởi B.
  - AE-02: workspace nghiên cứu công ty của A không lộ nguồn, báo cáo, hay email của B dù trùng tên công ty.
  - AE-03: lỗi Google Calendar của A thành trạng thái không khả dụng, không thành "không có sự kiện"; lịch của B không được đọc. Khi sửa, cập nhật `evals/deterministic/test_list_events.py` dòng 74–85 (`test_list_events_graceful_failure_of_one_source`): test đó đang khóa việc nuốt chuỗi `Google Calendar unavailable` khi lịch local còn sự kiện.
  - AE-04: `search_memory` và knowledge của A không trả fact hoặc chunk của B.
  - AE-05: hai user cùng yêu cầu một công ty thì ra hai báo cáo, hai nguồn, hai hash nội dung.
  - AE-06: agent nghiệp vụ từ chối connection id, thread id, report id và workspace id của người kia trước khi gọi nhà cung cấp.

### Phase 5 — Eval và AgentOps

- **Phụ thuộc:** Phase 2 đã redact JSONL và cột audit; Phase 4 đã có fixture hai user.
- **Phạm vi:** span OTel đúng cây, redact attribute OTel, chi phí gắn `owner_user_id`, eval không dùng chung state.
- **Cổng OPS:**
  - OPS-01: span con gắn parent của workflow. `test_tracer_init_keeps_otel_trace_api` chỉ chứng minh lệnh gán đè `_trace_api`; OPS-01 là cổng bổ sung cho parent span thật.
  - OPS-02: attribute OTel và usage ledger không chứa canary. JSONL và cột audit đã là cổng Phase 2, không giao lại cho OPS-02.
  - OPS-03: token và chi phí của một lượt LLM gắn đúng `owner_user_id`.
  - OPS-04: A không đọc trace của B. Admin chỉ thấy số liệu tổng hợp, không thấy nội dung.
  - OPS-05: eval hai user dùng home/database tách, không dùng `.pu` chung.
  - OPS-06: endpoint metrics không nhúng payload riêng tư.
- **Gỡ `xfail`, chỉ ở phase này:** `test_agentops_redacts_canary_in_otel` và `test_tracer_init_keeps_otel_trace_api`. Không gỡ marker JSONL hay cột audit.

### Phase 6 — Sẵn sàng production

- **Phụ thuộc:** Phase 1–5 đã xanh cổng riêng của chúng.
- **Phạm vi:** cổng phát hành chạy lại toàn bộ MU-01..MU-12 trên PostgreSQL, hai instance, và fixture A/B. Kiểm tra khóa mã hóa không nằm trong DB, role không có `BYPASSRLS`, và đường nhập `local-user` vẫn từ chối khi thiếu bản đồ. Xóa `InternalPrincipalSeam` theo mục 1.6 trước khi chạy cổng này; không còn đường test nào gắn principal bằng seam.
- **Cổng:** tất cả MU-01..MU-12 pass. Không còn `xfail` của Phase 0 trên các lỗi đã được các phase sau nhận sửa.
- **Chưa đủ để phát hành:** còn `xfail` đúng lý do, còn sink sót canary, hoặc còn đường đọc nhà cung cấp ngoài Tool Harness.

## 4. Thứ tự sửa các lỗi baseline

| Lỗi đã xác nhận ở Phase 0 | Marker | Phase gỡ marker |
| --- | --- | --- |
| Canary lọt JSONL trace | `test_agentops_redacts_canary_in_jsonl` | 2 |
| Canary lọt attribute OTel | `test_agentops_redacts_canary_in_otel` | 5 |
| Cột audit `reason`, `result_summary`, `error` chưa redact | `test_sqlite_tool_audit_columns_redact_canary` | 2 |
| `recover_inflight()` fail mọi hàng `executing` | `test_recover_inflight_preserves_other_owner_and_live_lease` | 2 |
| Đọc Gmail, Calendar, trang web ngoài Tool Harness, gồm ba callsite mục Phase 2 | các test harness trong file baseline | 2 |
| `Tracer.__init__` xóa `_trace_api` (chỉ lệnh gán đè) | `test_tracer_init_keeps_otel_trace_api` | 5 |
| `list_events` biến lỗi Google thành "No events found", kể cả test cũ dòng 74–85 | `test_list_events_surfaces_google_error_instead_of_empty_diary` và `test_list_events_graceful_failure_of_one_source` | 4 |

## 5. Tài liệu kèm

- Báo cáo Phase 0: `docs/phase0/BASELINE_REPORT.md`
- Nội dung issue để dán, nếu chưa tạo được trên GitHub: `docs/ROADMAP_ISSUES.md`
