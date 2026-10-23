# Nâng cấp và triển khai đa người dùng

**Production hiện chạy trên SQLite.** Dashboard (`pu/ops/dashboard.py`), CLI (`create_application` → `build_operational_persistence`), worker (`pu/ops/briefing.py`) và `AuthStore` (`pu/identity/session.py`) đều mở `$PU_HOME/state.db`. Không process phục vụ nào mở PostgreSQL. `PU_POSTGRES_DSN` chỉ được test đọc.

Schema `pu_phase1`, RLS và role `pu_app` trong `pu/persistence/postgres_schema.py` là hợp đồng đã được test. Chúng không phải ranh giới cô lập đang sống. Ranh giới hôm nay là kiểm tra owner trong ứng dụng: `current_principal`, `pu_current_owner()` / `current_owner_user_id` (`pu/identity/scope.py`), trigger SQLite 9006 và 9009, và file dưới `owners/<id>/`. Nối PostgreSQL vào process đang chạy là việc sau này. Mục 4 và mục 5 chỉ dùng cho lúc đó.

Hướng dẫn này bám mã đã merge qua Phase 6 (`docs/MULTI_USER_ARCHITECTURE_ROADMAP.md`). Mỗi lệnh, tên biến và hiệu ứng migration dưới đây được lấy từ source. Không có lệnh `pu migrate`.

## 1. Điều kiện

`pyproject.toml` khai báo `requires-python = ">=3.11"` và classifier 3.11, 3.12.

```bash
python --version
```

Extra tùy chọn, đúng tên trong `[project.optional-dependencies]`:

| Extra | Gói chính | Khi nào cần |
| --- | --- | --- |
| `postgres` | `psycopg[binary]>=3.1` | Gọi `postgres_schema.install` hoặc chạy test có `PU_POSTGRES_DSN` |
| `gmail` | Google API client, auth, oauthlib | `pu connect gmail` và đồng bộ Gmail |
| `gcal` | cùng họ Google | Google Calendar |
| `drive` | cùng họ Google | `pu connect drive` và import Drive |
| `tracing` | OpenTelemetry SDK + exporter OTLP, Arize Phoenix | `OTEL_EXPORTER_OTLP_ENDPOINT` hoặc `make trace` |
| `eval` | `pytest>=8.0`, `deepeval` | `pytest evals/deterministic` |
| `dev` | `pytest>=8.0`, `ruff==0.16.0` | lint và pytest |
| `sources` | `pypdf>=5.0` | đọc PDF nguồn |
| `pdf` | `xhtml2pdf` | render báo cáo PDF |

Gmail, Calendar và Drive không dùng chung một extra. Cài thiếu gói thì `connect` trả câu `... support is not installed — run: pip install -e '.[gmail]'` (hoặc `.[gcal]`, `.[drive]`).

## 2. Cài dependency

Từ gốc repo:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[postgres,gmail,gcal,drive,tracing,eval]'
```

`pu.config` gọi `find_dotenv(usecwd=True)` lúc import và `load_dotenv` file tìm được. Một dòng `PU_HOME=` trống trong `.env` thành biến rỗng; code dùng `os.getenv("PU_HOME", "") or ".pu"`, nên home vẫn là `.pu`.

File mẫu sinh bởi `scripts/generate_env_example.py` là `.env.example`. File đó không chứa OIDC, `PU_TOKEN_KEY` hay `PU_POSTGRES_DSN`.

## 3. Biến môi trường

Không có biến nào bắt buộc để process dashboard lắng nghe. Chat cần key của provider đang chọn. Đăng nhập trình duyệt cần đủ bộ OIDC. Mã hóa token OAuth trong bảng `oauth_connections` cần `PU_TOKEN_KEY`. `PU_POSTGRES_DSN` chỉ được test đọc.

### 3.1 PostgreSQL, khóa token, OIDC, cổng

| Biến | Bắt buộc? | Code đọc | Việc nó làm |
| --- | --- | --- | --- |
| `PU_POSTGRES_DSN` | Chỉ khi muốn chạy test Postgres | `os.environ` trong `test_phase1_identity_ownership.py`, `test_phase4_business_agents.py`, `test_phase6_multi_user_release.py` | DSN quản trị (role được `CREATE SCHEMA` / `CREATE ROLE`). Rỗng thì test skip. Ứng dụng không mở DSN này |
| `PU_TOKEN_KEY` | Cần để ghi ciphertext mới và để viết lại blob `enc1` | `pu/identity/crypto.py`, `pu/harness/audit.py` | Chuỗi khóa nằm ngoài DB. `encrypt` / giải `enc1` đòi `len(key) >= 16`, nếu không thì `TokenKeyError`. `redact_text` thay khóa bằng `[REDACTED]` khi độ dài từ 8 trở lên và khóa xuất hiện trong text |
| `PU_OIDC_AUTHORIZATION_ENDPOINT` | Cả năm biến OIDC dưới đây phải cùng khác rỗng thì `/api/auth/login` mới chạy | `pu/ops/dashboard.py` `_oidc_provider_from_env` | URL ủy quyền của nhà cung cấp |
| `PU_OIDC_TOKEN_ENDPOINT` | cùng điều kiện | cùng hàm | URL đổi authorization code |
| `PU_OIDC_CLIENT_ID` | cùng điều kiện | cùng hàm | `client_id` và audience kỳ vọng của id token |
| `PU_OIDC_REDIRECT_URI` | cùng điều kiện | cùng hàm | `redirect_uri` gửi ở cả bước ủy quyền và bước đổi code |
| `PU_OIDC_ISSUER` | cùng điều kiện | cùng hàm | Claim `iss` phải khớp nguyên chuỗi |
| `PU_OIDC_JWKS_URI` | Không, trừ khi id token là RS256 | cùng hàm, truyền vào `OidcProvider.jwks_uri` | `http_get` tải JWKS. RS256 không có URI thì `AuthError("jwks")` |
| `PU_OIDC_CLIENT_SECRET` | Không với client public; cần cho HS256 và khi nhà cung cấp đòi secret | cùng hàm | Nếu khác rỗng, `exchange_code` thêm `client_secret` vào form. HS256 ký bằng secret này |
| `PU_HOME` | Không. Mặc định `.pu` | `pu/config.py` | Thư mục state, token, trace |
| `PU_DASHBOARD_PORT` | Không | `pu/ops/dashboard.py` `main` | Cổng bắt đầu. Sau đó tới `PORT`, rồi hằng số `9000` |
| `PORT` | Không | cùng chỗ, chỉ khi `PU_DASHBOARD_PORT` trống | Cổng dự phòng |

Thiếu một trong năm biến OIDC bắt buộc thì `GET /api/auth/login` trả `400` JSON `{"error":"oidc_not_configured","required":[...],"missing":[...]}`. `required` và `missing` chỉ là tên biến, không có giá trị. `GET /api/auth/callback` trong trường hợp đó trả `400` HTML, không tạo phiên.

Sinh khóa token bên ngoài repo và đưa vào môi trường. Đừng ghi giá trị vào file được commit. Test `test_release_no_xfail_and_token_key_is_not_committed` quét file theo dõi và fail nếu thấy gán `PU_TOKEN_KEY` bằng một giá trị dài từ 16 ký tự trở lên mà không phải biến shell.

```bash
export PU_TOKEN_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

`install()` nhận mật khẩu role bằng tham số `password`. Không có biến môi trường nào trong ứng dụng chứa mật khẩu đó.

### 3.2 Telemetry và SLO

| Biến | Mặc định | Việc nó làm |
| --- | --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | rỗng | `Settings.otel_endpoint`. Khác rỗng thì tracer còn xuất OTLP. Cần extra `tracing`. JSONL vẫn ghi khi biến này trống |
| `PU_SLO_LLM_P95_MS` | `15000` | Ngưỡng p95 LLM cho SLO |
| `PU_SLO_TOOL_ERROR_RATE` | `0.05` | Ngưỡng tỉ lệ lỗi tool |
| `PU_SLO_WORKFLOW_SUCCESS_RATE` | `0.95` | Ngưỡng thành công workflow |
| `PU_SLO_APPROVAL_FAILURE_RATE` | `0.05` | Ngưỡng lỗi approval |
| `PU_SLO_SECURITY_BLOCKS_MAX` | `25` | Trần số lần security chặn |

Chủ local (không có request HTTP, hoặc phiên trùng `identity_local.user_id`) ghi `$PU_HOME/traces/<ngày>.jsonl` và `$PU_HOME/usage.jsonl`. Phiên của user khác ghi `owners/<user_id>/traces/` và `owners/<user_id>/usage.jsonl`. `PLATFORM_ADMIN` và request bị từ chối không nhận nội dung trace (`telemetry_scope` đặt `admin` hoặc `denied`). `pu/ops/tracing.py` đưa sự kiện qua `redact` / `redact_text` trước khi ghi.

Stack local trong repo:

```bash
docker compose -f observability/docker-compose.yml up -d
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 python -m pu dashboard
```

Cổng trong `observability/docker-compose.yml`: OTLP `4317` và `4318`, Tempo `3200`, Prometheus `9090`, Grafana `3000`. `make trace` chạy `python -m phoenix.server.main serve` (cần extra `tracing`).

`GET /metrics` trên Host loopback không cần cookie. Handler gọi `connect()`, nên request đó cũng áp migration SQLite, rồi trả text Prometheus từ `repo.aggregate()`.

### 3.3 Provider và tích hợp

`PU_PROVIDER` mặc định `anthropic`. Key riêng của provider được dùng khi `PU_API_KEY` trống (`pu/providers/llm/factory.py`).

| `PU_PROVIDER` | Key | Base URL |
| --- | --- | --- |
| `anthropic` | `ANTHROPIC_API_KEY` | `PU_ANTHROPIC_BASE_URL` |
| `openai` | `OPENAI_API_KEY` | `PU_OPENAI_BASE_URL` |
| `openrouter` | `OPENROUTER_API_KEY` | `PU_OPENROUTER_BASE_URL` (mặc định catalog `https://openrouter.ai/api/v1`) |
| `deepseek` | `DEEPSEEK_API_KEY` | `PU_DEEPSEEK_BASE_URL` (mặc định `https://api.deepseek.com`) |
| `glm` | `ZAI_API_KEY` | `PU_GLM_BASE_URL` (mặc định `https://api.z.ai/api/paas/v4`) |
| `gemini` | `GEMINI_API_KEY` | `PU_GEMINI_BASE_URL` (mặc định `https://generativelanguage.googleapis.com/v1beta/openai/`) |

`PU_BASE_URL` không còn được đọc.

| Biến | Mặc định | Việc nó làm |
| --- | --- | --- |
| `PU_API_KEY` | rỗng | Key ghi đè key của provider đang chọn |
| `PU_MODEL` | rỗng, rồi default của provider | Model chính |
| `PU_SMALL_MODEL` | rỗng, rồi default của provider | Model nhỏ (cổng truy hồi, tóm tắt) |
| `PU_DISABLED_PROVIDERS` | rỗng | Danh sách id cách nhau bởi dấu phẩy, ẩn khỏi bộ chọn |
| `PU_LLM_TIMEOUT` | `120` | Timeout giây của client LLM |
| `PU_GMAIL` | tắt | Bật khi giá trị là `1`, `true` hoặc `yes`. Khi bật, `build_registry` đăng ký thêm tool sync Gmail |
| `PU_GMAIL_LABEL` | `INBOX` | Nhãn kéo thư |
| `PU_GMAIL_MAX_MESSAGES` | `50` | Trần số thư mỗi lần sync |
| `PU_GOOGLE_CALENDAR` | tắt | Cùng ba giá trị `1` / `true` / `yes`. Bật ghi sự kiện sang Google; SQLite và `calendar.ics` vẫn là nguồn local |
| `PU_GOOGLE_CALENDAR_ID` | `primary` | Id lịch Google khi ghi |
| `PU_DRIVE` | tắt ở registry Connections | Registry coi mọi chuỗi khác rỗng là bật. Route `/api/drive` không đọc biến này trước khi connect/list/import |
| `TAVILY_API_KEY` | rỗng | Key tìm web. `PU_SEARCH_API_KEY` là tên dự phòng cùng chỗ đọc |
| `PU_SEARCH_API_KEY` | rỗng | Dùng khi `TAVILY_API_KEY` trống |

Ba giá trị bật của `PU_GMAIL`, `PU_GOOGLE_CALENDAR` và `PU_GRAPH_WORKFLOWS` so khớp đúng chuỗi `1`, `true`, `yes`. `True` hay `YES` không được tính là bật.

### 3.4 Vòng lặp, bộ nhớ, báo cáo, phiên local

| Biến | Mặc định | Việc nó làm |
| --- | --- | --- |
| `PU_MAX_ITERATIONS` | `10` | Trần vòng tool của một lượt |
| `PU_MAX_TOKENS` | `8192` | Trần token đầu ra |
| `PU_HISTORY_TURNS` | `12` | Số lượt gần nhất đưa vào prompt |
| `PU_CONSOLIDATE_EVERY` | `6` | Chu kỳ cô đặc bộ nhớ |
| `PU_RETRIEVAL_TOP_K` | `4` | Số fact kéo lại |
| `PU_TOOL_RATE_LIMIT_PER_MINUTE` | `120` | Trần gọi tool mỗi phút |
| `PU_TOOL_READ_RETRIES` | `2` | Số lần thử lại tool đọc. Tool ghi không tự thử lại |
| `PU_APPROVAL_TTL_MINUTES` | `60` | TTL của một approval |
| `PU_GRAPH_WORKFLOWS` | tắt | `1` / `true` / `yes` thì phân loại tin nhắn bằng graph trước |
| `PU_REPORT_QUALITY_MIN_SCORE` | `0.72` | Ngưỡng điểm chất lượng báo cáo |
| `PU_REPORT_MIN_COMPLETENESS` | `0.65` | Ngưỡng completeness |
| `PU_REPORT_MIN_SOURCE_COVERAGE` | `0.80` | Ngưỡng coverage nguồn |
| `PU_REPORT_FRESHNESS_DAYS` | `30` | Cửa sổ độ tươi của nguồn |
| `PU_REPORT_JUDGE` | tắt | `1` / `true` / `yes` bật judge trong workflow nghiên cứu |
| `PU_REPORT_JUDGE_MODEL` | rỗng | Model judge của workflow, nếu đặt |
| `PU_SESSION_IDLE_MINUTES` | `60` | Khoảng im lặng trước khi chat dashboard mở thread mới |
| `PU_EDITOR` | trống, rồi `cursor`, rồi `code` | CLI mở file từ dashboard |
| `PU_JUDGE_PROVIDER` | `openai` | Provider của judge eval (`pu/ops/judge.py`) |
| `PU_JUDGE_MODEL` | `gpt-5.6-sol` | Model judge eval |
| `PU_JUDGE_CONCURRENCY` | `2` | Số judge chạy song song |
| `PU_DELEGATE_ENV_DENY` | rỗng | Tên biến, cách nhau bởi dấu phẩy, bị gỡ khỏi môi trường subprocess |
| `PU_RUN_LIVE_EVALS` | không đặt | Đúng `1` thì một số test trong `test_tool_trigger.py` hết skip |

## 4. Hợp đồng PostgreSQL `pu_app` (chưa gắn vào process nào)

**Production hiện chạy trên SQLite.** `build_operational_persistence` trả `SQLiteDatabase`. Dashboard, CLI, worker và `AuthStore` không gọi `psycopg`. File trong `pu/` mở driver đó để tạo schema chỉ có `pu/persistence/postgres_schema.py`. `pu/agents/isolation.py` nhận ra connection psycopg nếu được đưa sẵn; ứng dụng không tự mở connection đó.

RLS và `pu_app` không che dữ liệu mà dashboard đang phục vụ. Cô lập đang sống là kiểm tra owner ở tầng ứng dụng. Tạo schema `pu_phase1` rồi trỏ ứng dụng vào `pu_app` không bật cô lập, vì không có đường đọc schema đó.

`install` là hợp đồng mà test gọi. Không có file SQL riêng. Hàm từ chối nếu `password` trống (`ValueError: password is required; there is no default database password`). Tên role chỉ được chữ, số và `_`. Phần `pu_app` và Supabase ở mục 5 chỉ dành cho lúc PostgreSQL được nối vào process.

Hành vi khi schema `pu_phase1` đã tồn tại:

- Đếm mọi hàng trong schema. Nếu có hàng và `replace_existing` là `False` (mặc định), ném `RuntimeError` và không `DROP SCHEMA`.
- Nếu schema tồn tại nhưng rỗng, hoặc `replace_existing=True`, chạy `DROP SCHEMA IF EXISTS pu_phase1 CASCADE` rồi tạo lại.

Test deterministic truyền `replace_existing=True`. Một lần chạy suite với `PU_POSTGRES_DSN` xóa schema `pu_phase1` bốn lần. Chỉ trỏ biến đó vào database trống, dùng xong thì bỏ. Chi tiết ở mục 11.

`CREATE ROLE` không chạy trong transaction. `install` bật `autocommit` nếu connection đang tắt, rồi trả lại chế độ cũ.

Role được tạo hoặc sửa thành:

```text
LOGIN PASSWORD <password>
NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
```

Role đã tồn tại thì `ALTER ROLE` cùng các cờ đó. Quyền cấp cho role:

- `GRANT USAGE ON SCHEMA pu_phase1`
- `GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA pu_phase1`
- `GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA pu_phase1`
- `ALTER ROLE pu_app SET search_path TO pu_phase1`

Mỗi bảng trong `PRIVATE_TABLES` nhận `CHECK (owner_user_id <> '')` tên `<bảng>_owner_nonempty`, `ENABLE ROW LEVEL SECURITY`, `FORCE ROW LEVEL SECURITY`, và policy `pu_owner_isolation` với `USING` lẫn `WITH CHECK` bằng `owner_user_id = current_setting('pu.owner_user_id', true)`. Bảng `users` không nằm trong `PRIVATE_TABLES`. Nó có policy `pu_user_self`: `id` phải bằng cùng setting đó.

Comment ở đầu module: kết nối superuser bỏ qua RLS kể cả khi `FORCE ROW LEVEL SECURITY` đã bật. Khi PostgreSQL được nối, connection của ứng dụng phải là `pu_app` (`NOSUPERUSER`, `NOBYPASSRLS`). `set_owner` chạy `SELECT set_config('pu.owner_user_id', %s, true)`. Không có setting này thì policy không thấy hàng.

Đoạn dưới là cách test gọi `install`, không phải bước khởi động dashboard. Mật khẩu là tham số, không phải biến mà app đọc:

```python
import os
import psycopg
from pu.persistence.postgres_schema import install

admin = psycopg.connect(os.environ["PU_POSTGRES_DSN"])
install(admin, role="pu_app", password="đặt-một-mật-khẩu")
admin.close()
```

Để nguyên `replace_existing=False` trên database đã có dữ liệu. Test kết nối lại bằng `user="pu_app"`, cùng mật khẩu đã truyền, `dbname` lấy từ DSN quản trị, `port` từ DSN hoặc `5432`. Nếu `host` của DSN là socket (`/...`), test đổi host thành `127.0.0.1`.

## 5. Supabase, chỉ khi PostgreSQL đã được nối

Mục này không phải bước triển khai hôm nay. Dashboard, CLI, worker và `AuthStore` không mở Postgres. Tạo `pu_phase1` trên Supabase không đổi ranh giới cô lập đang chạy.

Khi một process thực sự kết nối PostgreSQL, connection đó dùng role `pu_app` do `install` tạo (`LOGIN`, `NOSUPERUSER`, `NOBYPASSRLS`, `NOCREATEDB`, `NOCREATEROLE`). Kết nối đó không dùng role `postgres` và không dùng `service_role`: comment của module nói superuser vẫn bỏ qua RLS khi đã `FORCE`. Schema của hợp đồng là `pu_phase1`, không phải `public`. Policy chỉ nhận owner từ `set_config('pu.owner_user_id', ...)`.

Repo không chứa test Supabase và không kiểm tra cờ role trên một project hosted. `PU_POSTGRES_DSN` trong test là DSN quản trị để `CREATE SCHEMA` / `CREATE ROLE`, không phải DSN của `pu_app` và không phải DSN của ứng dụng.

## 6. Sao lưu trước khi migrate

Repo không có lệnh backup.

Dừng dashboard và worker trước. `pu/ops/reset.py` nói rõ phải dừng chúng để connection SQLite đang mở không ghi lại state cũ; cùng lý do áp dụng trước khi copy.

SQLite bật `PRAGMA journal_mode=WAL` trong `SQLiteDatabase.connect`. Copy cả thư mục `PU_HOME` khi process đã dừng, gồm ít nhất:

- `state.db`, `state.db-wal`, `state.db-shm`
- token ở gốc home (`gmail-token.json`, `google-token.json`, `drive-token.json`) và `credentials.json`
- `calendar.ics`
- `knowledge/` nếu có
- `traces/`, `usage.jsonl`, `outbox/`

Migration 9005 đổi tên bảng thành `<bảng>__pre_owner`, copy, rồi xóa bản copy khi số hàng khớp. Bản `__pre_owner` không phải bản sao lưu của operator: lần mở sau sẽ xóa nó nếu copy đã đủ hàng. Giữ bản copy thư mục home ở ngoài `PU_HOME`.

Dump PostgreSQL chỉ khi bạn cố ý gọi `install` trên một database có dữ liệu cần giữ. Suite test với `PU_POSTGRES_DSN` không thuộc trường hợp đó: nó cần database trống vì `replace_existing=True` xóa schema `pu_phase1`. Repo không bọc `pg_dump`. Gọi `install` không chuyển storage của dashboard.

Đặt `PU_TOKEN_KEY` trước lần mở database đầu tiên nếu bảng `oauth_connections` có thể chứa blob `enc1`. Thiếu khóa thì 9007 vẫn ghim digest, nhưng ciphertext không được viết lại (mục 7).

## 7. Chạy migration

Không có CLI migrate. `SQLiteMigrationRunner.apply` chạy trong `pu.db.connect` và trong `build_operational_persistence`. `python -m pu` đi qua `create_application`, nên áp migration trước vòng chat. Dashboard gọi `connect` ở các route dùng `state.db`, và `GET /metrics` gọi `connect` cả khi không có phiên.

Áp migration và in phiên bản trước khi mở cổng:

```python
from pu.config import load_settings
from pu.db import connect

home = load_settings().ensure_home()
conn = connect(home)
for row in conn.execute("SELECT version, name FROM schema_migrations ORDER BY version"):
    print(row["version"], row["name"])
local = conn.execute(
    "SELECT user_id, workspace_id FROM identity_local WHERE singleton = 1"
).fetchone()
print(local["user_id"], local["workspace_id"])
conn.close()
```

`schema_migrations` chỉ `INSERT`. Runner bỏ qua `version` đã có và không có bước xuống.

Các version và việc chúng làm:

| Version | Tên | Hiệu ứng |
| --- | --- | --- |
| 9001 | `workflow_checkpoints_agentops_and_durable_audit` | Tạo `workflow_runs`, checkpoint, `agent_events`, `tool_audit_events` |
| 9002 | `customer_research_workspaces` | Workspace nghiên cứu và bảng con |
| 9003 | `automatic_partner_briefing` | `briefing_state`, `briefing_seen`, `briefing_jobs` |
| 9004 | `bounded_briefing_retries` | Thêm `attempts`, `next_attempt` |
| 9005 | `owner_user_id_personal_workspace_and_composite_fks` | Xem bên dưới |
| 9006 | `idempotent_owner_match_triggers` | Trigger khớp owner, tạo bằng `IF NOT EXISTS` |
| 9007 | `reencrypt_legacy_oauth_tokens` | Ghim tập `enc1`, rồi viết lại nếu có khóa |
| 9008 | `briefing_fingerprint_per_owner` | `UNIQUE(fingerprint, owner_user_id)` trên `briefing_jobs` |
| 9009 | `reject_empty_owner_user_id` | Backfill owner trống lần nữa, rồi cấm ghi owner trống |

9005 (`apply_ownership_migration`):

- Nếu còn bảng `*__pre_owner` từ lần trước bị đứt, `_resume_interrupted` khôi phục bảng sống từ backup khi bảng sống thiếu hoặc ngắn hơn. Nếu bảng sống dài hơn backup, ném `RuntimeError` và không ghi version 9005.
- `ensure_local_principal` tạo một user UUID và một workspace nếu `identity_local` chưa có hàng `singleton = 1`.
- Thêm `owner_user_id` cho bảng riêng trong `OWNED_TABLES`, rồi `UPDATE ... SET owner_user_id = ? WHERE owner_user_id = ''` bằng user đó.
- Unique `(id, owner_user_id)` trên `workflow_runs`, `research_workspaces`, `knowledge_sources`. Unique `(report_id, owner_user_id)` trên `workspace_reports` (`_unique_owner_key(..., "report_id")`).
- Dựng lại checkpoint, bảng con workspace, khóa briefing, khóa chính `crm_emails (gmail_id, owner_user_id)`, khóa ngoại `knowledge_chunks`, và FTS có cột `owner_user_id UNINDEXED`.
- Còn bảng `__pre_owner` thì không ghi version.

9006 cài trigger `BEFORE INSERT/UPDATE` trên `agent_events`, `tool_audit_events`, `proposed_actions`: `workflow_id` phải thuộc `workflow_runs` cùng `owner_user_id`. Tên trigger có hậu tố `_v1`. Trigger cũ không hậu tố bị `DROP` sau khi bản mới đã tạo. Thêm `episodes_au` nếu bảng episodes còn.

9007, chỉ lần đầu version này được ghi:

- `pin_legacy_oauth_tokens` thêm cột `migration_pending` và `legacy_digest` nếu thiếu.
- Mỗi hàng `enc1` chưa có digest nhận `legacy_digest = sha256` của đúng ciphertext đó và `migration_pending = 1`. Digest không bị xóa sau này. Hàng `enc1` xuất hiện sau lần ghim này không được thêm vào tập.
- `migrate_legacy_oauth_tokens` chạy ngay trong 9007 và lại chạy ở cuối mọi `apply()` sau đó, cùng lúc `AuthStore` mở. Nó chỉ đụng hàng đã có `legacy_digest`.
- Có `PU_TOKEN_KEY` dài từ 16 ký tự, digest khớp, giải mã được: ciphertext thành `enc2` (AES-GCM, HKDF, AAD là `owner_user_id` và connection id) và `migration_pending = 0`. Digest giữ nguyên.
- Thiếu khóa, digest lệch, hoặc giải mã lỗi: `migration_pending = 1`, ciphertext giữ nguyên. `use_oauth_connection` trả `None` với blob `enc1` và không gọi nhà cung cấp.

9008 dựng lại `briefing_jobs` nếu ràng buộc unique chưa phải `(fingerprint, owner_user_id)`.

9009 backfill owner trống thêm một lần bằng cùng user local, rồi tạo trigger `BEFORE INSERT` và `BEFORE UPDATE`. Owner `NULL` hoặc `''` thì `RAISE(ABORT, 'owner_user_id is required')`. SQLite không thêm `CHECK` vào cột có sẵn mà không dựng lại bảng; trigger là chốt trên SQLite. `CHECK` thật nằm ở `install()` của PostgreSQL, không nằm trong runner 9009.

## 8. Home một người dùng sang `owners/<id>/`

Không có lệnh chuyển cả cây file. Hàng SQL và file đi hai đường khác nhau.

### 8.1 Hàng trong `state.db`

Lần `connect` đầu tiên tạo user trong `identity_local` nếu chưa có, rồi 9005 và 9009 gán mọi `owner_user_id` đang trống cho user đó. Các bảng gồm `facts`, `episodes`, `chat_log`, `crm_emails`, `knowledge_sources`, `knowledge_chunks`, `calendar_events`, workflow, workspace nghiên cứu và briefing.

`import_legacy_rows` trong `pu/identity/legacy_import.py` là hàm thư viện, không gắn CLI. Nó chỉ chèn một lô có nhãn `legacy_owner` khi map nhãn đó sang `user_id` đã có trong bảng `users`. Thiếu map thì cả lô bị `LegacyImportRejected`. Nó không đọc thư mục home.

CLI `python -m pu` không có request HTTP nên `current_principal` dùng đúng user `identity_local`. Dữ liệu cũ còn thấy trên terminal.

`complete_oidc` không gắn `sub` vào `identity_local`. `sub` mới được `provision_user` một UUID khác và ghi vào `oidc_subjects`. Phiên trình duyệt đó không thấy hàng của user local. Repo không có lệnh map một `sub` OIDC sang user đã có.

### 8.2 Token, lịch, knowledge

File mới qua `write_owned_bytes` chỉ nằm dưới `owners/<owner_user_id>/`. File cũ ở gốc home không bị di chuyển hàng loạt và không bị xóa khi có bản mirror.

Token mà tool Google thực sự mở:

- `gmail-token.json` (`pu/tools/gmail.py`)
- `google-token.json` (`pu/tools/google_calendar.py`)
- `drive-token.json` (`pu/tools/google_drive.py`)

`owned_token_path` trả về:

- bản `owners/<id>/<tên>` nếu file đó đã tồn tại;
- nếu không, và owner hiện tại là user `identity_local`, thì file gốc `$PU_HOME/<tên>`;
- user khác nhận `owners/<id>/<tên>` và không nhận file gốc.

Request đã bind mà không có principal ném `PermissionError` trước khi trả path. `credentials.json` vẫn được `connect()` đọc tại `$PU_HOME/credentials.json`. Đó là client OAuth dùng chung, không phải token từng user.

`calendar.ics` vẫn được `create_event` ghi tại `$PU_HOME/calendar.ics`, rồi `claim_private_file` viết sidecar `calendar.ics.owner` và `note_written` copy sang `owners/<id>/calendar.ics`. File gốc còn lại. Lần đọc harness dùng `private_file`: bản trong `owners/<id>/` thắng nếu có; không có thì user local vẫn đọc file gốc. Hàng `calendar_events` là dữ liệu SQL đã backfill, tách khỏi file ICS.

`knowledge_sources` và `knowledge_chunks` nằm trong SQLite và được gán owner ở 9005/9009. Reindex của dashboard (`POST /api/knowledge`, `op` = `reindex`) chỉ đọc `owners/<user_id>/knowledge`. Không có hàm nào copy `$PU_HOME/knowledge/`. Muốn reindex thấy file cũ thì tự copy sang đúng thư mục đó, rồi gọi reindex bằng một principal. Ngoài request, principal đó là user local:

```python
from pu.config import load_settings
from pu.db import connect
from pu.identity.files import database_local_owner, owner_root
from pu.memory.knowledge import reindex_folder

home = load_settings().ensure_home()
conn = connect(home)
owner = database_local_owner(home)
print(reindex_folder(conn, owner_root(home, owner) / "knowledge"))
conn.close()
```

`reindex_folder` chỉ nhận `.md` và `.txt`.

Danh sách tên file riêng trong `PRIVATE_RELATIVE_PATHS`: `usage.jsonl`, `eval_runs.jsonl`, `calendar.ics`, `SOUL.md`, `MEMORY.md`, `models.json`, `.env`, `credentials.json`, `gmail-token.json`, `gmail-send-token.json`, `calendar-token.json`, `google-token.json`, `google-calendar-token.json`, `drive-token.json`, `token.json`. Trace của user local ở `$PU_HOME/traces/`. Trace của user khác ở `owners/<id>/traces/`. Không có bước gộp hai thư mục này.

## 9. Chạy dashboard và các lệnh khác

Process chỉ bind `127.0.0.1`. Không có biến chọn địa chỉ lắng nghe. Cổng là `PU_DASHBOARD_PORT`, không có thì `PORT`, không có thì `9000`. Cổng bận thì thử tiếp tới chín cổng sau, rồi `SystemExit` nếu cả dải đều bận.

```bash
python -m pu dashboard
```

Tương đương: `python -m pu.ops.dashboard` và `make dashboard`. Dòng in ra là `PU dashboard → http://localhost:<cổng>  (Ctrl-C to stop)`. `main` cũng gọi `briefing_service(..., start=True)` trước `serve_forever`.

Các lệnh khác trong `pu/__main__.py`:

```bash
python -m pu                  # chat terminal, dùng owner local
python -m pu connections
python -m pu brief
python -m pu worker
python -m pu connect gmail
python -m pu connect drive
```

Route Python không tự nạp lại. Sau khi đổi code, dừng process và chạy lại. File tĩnh có `Cache-Control: no-cache`.

## 10. Đăng nhập, 401, loopback và host khác

Cookie phiên là `pu_session`. Cookie giao dịch OIDC là `pu_oidc`. Cả hai được `format_set_cookie` gắn `Path=/; HttpOnly; Secure; SameSite=Lax`. Phiên sống `Max-Age=43200` (12 giờ). Cookie OIDC sống `Max-Age=600`. Không có nhánh tắt `Secure` cho HTTP.

`host_is_loopback` chỉ đúng khi `Host` là `127.0.0.1`, `localhost` hoặc `::1`, có thể kèm cổng (`localhost:9000`, `[::1]:9000`). Host rỗng không phải loopback. Tên khác, kể cả tên trỏ về 127.0.0.1, bị từ chối. Comment trong `evaluate_on_home` gọi đây là chặn DNS rebinding trên đường không có cookie.

Không có cookie:

- Host loopback: `evaluate` không reject và không gắn principal.
- Host khác: reject lý do `loopback_host`.

Có cookie: host không bị xét lại. Hàng `auth_sessions` còn sống thì principal là `owner_user_id` của hàng đó. Hàng mất hoặc đã `revoked_at` thì lý do `session_revoked`. `POST` khi đã có phiên còn đòi header `X-CSRF-Token` trùng `csrf_token` của hàng. Thiếu hoặc lệch thì lý do `csrf`.

Mã HTTP từ `Handler`:

| Yêu cầu | Kết quả |
| --- | --- |
| `GET` Host không loopback, không cookie | `403` `{"error":"loopback_host"}`. HTML, `/static` và `/metrics` cũng không tới |
| `GET` loopback, không cookie, path không phải `/api/` | `200`. Trang và file tĩnh vẫn ra. `/metrics` cũng vậy và còn gọi `connect()` |
| `GET` `/api/...` loopback, không cookie, trừ ba path auth bên dưới | `401` `{"error":"no authenticated principal"}` |
| `POST` `/api/...` loopback, không cookie | `401` cùng lỗi đó |
| `GET /` hoặc `GET /static/...` khi cookie phiên đã thu hồi | `200` shell đăng nhập và file tĩnh. Không gắn principal. `/static/../` không thuộc shell |
| `GET` khác khi cookie phiên đã thu hồi, gồm `/api/...` và `/metrics` | `401` `{"error":"session_revoked"}` |
| `POST` cookie không còn phiên | `403` `{"error":"session_revoked"}`. Nhánh `POST` luôn dùng 403 khi `evaluate` reject |
| `POST` phiên sống, CSRF thiếu hoặc sai | `403` `{"error":"csrf"}` |
| `GET /api/auth/login` khi thiếu OIDC | `400` JSON `oidc_not_configured`, kèm `required` và `missing` |
| `GET /api/auth/login` khi đủ OIDC | `200` `{"authorization_url": ...}` và `Set-Cookie: pu_oidc` |
| `GET /api/auth/callback` thành công | `302` `Location: /#overview`. `Set-Cookie` phiên và `pu_oidc` với `Max-Age=0`. Body rỗng. Không có `csrf_token` trong URL |
| `GET /api/auth/callback` lỗi | `400` HTML tiếng Việt. Không `Set-Cookie: pu_session` |
| `GET /api/auth/csrf` phiên sống | `200` `{"csrf_token","user_id"}` |
| `GET /api/auth/csrf` khi không có phiên sống | `401` `{"error":"session_revoked"}` |
| `POST /api/auth/logout` đủ phiên và CSRF | `200` `{"ok": true}`, cookie phiên `Max-Age=0`, hàng ghi `revoked_at` |

Ba path không đòi principal: `GET /api/auth/login`, `GET /api/auth/callback`, `GET /api/auth/csrf`. Chúng vẫn phải qua `evaluate` trước, nên Host không loopback mà không có cookie thì nhận `403 loopback_host` chứ không tới được bước login.

Màn hình đăng nhập nằm trong `pu/ops/static/index.html` (`body` có class `logged-out` cho tới khi phiên được xác nhận) và `pu/ops/static/js/auth.js`. CSS ẩn nav, nội dung và dock khi class đó còn. Trang tĩnh không nhúng dữ liệu user.

Luồng trên giao diện:

1. Mở `/` khi chưa có cookie: HTML hiện nút `Đăng nhập với Google`. Chưa có dữ liệu user.
2. Nút gọi `GET /api/auth/login`. Nếu `oidc_not_configured`, màn hình liệt kê `required` (năm biến `PU_OIDC_AUTHORIZATION_ENDPOINT`, `PU_OIDC_TOKEN_ENDPOINT`, `PU_OIDC_CLIENT_ID`, `PU_OIDC_REDIRECT_URI`, `PU_OIDC_ISSUER`). Nếu có `authorization_url` dạng `http` hoặc `https`, trình duyệt chuyển tới URL đó. `fetch` nhận `Set-Cookie: pu_oidc` trước khi rời trang.
3. Nhà cung cấp chuyển về callback. Thành công thì trình duyệt theo `302` tới `/#overview`. JS gọi `GET /api/auth/csrf`, giữ `csrf_token` trong bộ nhớ trang, hiện `user_id` và nút `Đăng xuất`.
4. Mọi `POST` từ giao diện đi qua `puMutateHeaders`, nên có `X-CSRF-Token`. Cookie `pu_session` là HttpOnly: JS không đọc `document.cookie` cho phiên và không ghi id token vào `localStorage`.
5. `401`, hoặc body `session_revoked` (kể cả `POST` trả `403`), xóa dữ liệu đang vẽ và hiện lại màn hình đăng nhập.
6. `Đăng xuất` là `POST /api/auth/logout` kèm CSRF. Phiên bị thu hồi. Lần gọi API sau thấy lại màn hình đăng nhập.

Luồng máy chủ:

1. `GET /api/auth/login` tạo hàng `oidc_transactions` (state, PKCE S256, nonce), trả `{"authorization_url": ...}` và `Set-Cookie: pu_oidc=...`.
2. URL ủy quyền có `response_type=code`, `scope=openid`, `code_challenge_method=S256`.
3. Nhà cung cấp chuyển về `GET /api/auth/callback?code&state` kèm cookie `pu_oidc`.
4. `complete_oidc` xóa giao dịch, đổi code, kiểm tra id token (`iss`, `aud`, `azp` khi có nhiều audience hoặc khi `azp` lệch client, `exp` với lệch 60 giây, `nbf`, `nonce`, `sub`). HS256 dùng client secret. RS256 dùng JWKS.
5. `sub` cũ lấy user đã lưu. `sub` mới được cấp user và workspace mới.
6. Response `302` tới `/#overview`, `Set-Cookie` phiên, và cookie `pu_oidc` với `Max-Age=0`. Body không chứa `csrf_token`. CSRF lấy bằng `GET /api/auth/csrf` sau khi trang tải lại.
7. Callback lỗi (`state`, `nonce`, `exp`, và các mã khác của `AuthError`) trả HTML, không phát hành `pu_session`.
8. Mọi `POST` đổi trạng thái gửi `X-CSRF-Token` và cookie `pu_session`.
9. `POST /api/auth/logout` cần phiên và CSRF. Hàng bị ghi `revoked_at`. Cookie phiên bị xóa. Lần sau là `session_revoked`.

`POST` còn trả `403` body rỗng khi có `Origin` mà netloc khác `Host` hoặc scheme khác đúng chuỗi `http`, hoặc khi `Sec-Fetch-Site` là `cross-site`. Scheme `https` không được chấp nhận ở chỗ này. Server không có nhánh TLS.

`SameSite=Lax` được chọn để cookie `pu_oidc` còn trên redirect `GET` từ nhà cung cấp. `Lax` không thay CSRF.

## 11. Kiểm tra bằng pytest

Cài extra `eval` hoặc `dev` để có pytest. Cài extra `postgres` trước khi đặt `PU_POSTGRES_DSN`; nếu không, `test_release_postgres_check_rejects_empty_owner` import `psycopg` và fail, trong khi test Phase 1 và Phase 4 skip khi thiếu gói.

Không đặt `PU_POSTGRES_DSN`:

```bash
python -m pytest -q evals/deterministic
```

`make eval` là cùng lệnh. Bốn test sau skip, suite còn lại phải xanh:

- `evals/deterministic/test_phase1_identity_ownership.py::test_mu07_rls_hides_other_owner_and_role_cannot_bypass` — `PostgreSQL unavailable: set PU_POSTGRES_DSN to run MU-07`
- `evals/deterministic/test_phase4_business_agents.py::test_hidden_postgres_row_is_refused_before_provider` — `PostgreSQL unavailable: set PU_POSTGRES_DSN`
- `evals/deterministic/test_phase6_multi_user_release.py::test_release_mu07_postgres_role_has_no_bypassrls` — cùng câu của MU-07
- `evals/deterministic/test_phase6_multi_user_release.py::test_release_postgres_check_rejects_empty_owner` — cùng câu của MU-07

Chỉ đặt `PU_POSTGRES_DSN` vào một database trống, tạo riêng để chạy test rồi bỏ. Một lần `pytest evals/deterministic` với biến này gọi `install(..., replace_existing=True)` bốn lần, nên `DROP SCHEMA pu_phase1 CASCADE` chạy bốn lần:

- `test_mu07_rls_hides_other_owner_and_role_cannot_bypass` (Phase 1)
- `test_hidden_postgres_row_is_refused_before_provider` (Phase 4)
- `test_release_mu07_postgres_role_has_no_bypassrls` (Phase 6) gọi lại đúng hàm test Phase 1 ở trên, nên `install` chạy thêm một lần
- `test_release_postgres_check_rejects_empty_owner` (Phase 6, kiểm tra `CHECK`)

Mật khẩu fixture là `pu-phase1-fixture` cho ba lần đầu (Phase 1, Phase 4, và lần Phase 6 gọi lại Phase 1) và `pu-phase6-fixture` cho test `CHECK`. `connect_timeout` là 3 giây.

Phase 1 và Phase 4 skip khi `psycopg.connect` ném `psycopg.Error`. Lần Phase 6 gọi lại Phase 1 đi cùng đường skip đó. Test `CHECK` của Phase 6 không skip khi DSN sai hoặc máy chủ từ chối kết nối: `psycopg.connect` nằm ngoài `pytest.skip`, nên DSN hỏng làm test đó lỗi thật. Thiếu gói `psycopg` mà vẫn đặt DSN thì test `CHECK` fail lúc import; Phase 1 và Phase 4 skip.

```bash
PU_POSTGRES_DSN="postgresql://<admin>:<mật-khẩu>@127.0.0.1:5432/<db-trống>" \
  python -m pytest -q evals/deterministic
```

Kỳ vọng thêm khi DSN nối được: role `pu_app` có `rolsuper` và `rolbypassrls` đều false; mọi bảng `PRIVATE_TABLES` bật RLS và force RLS; `pu_app` không đọc hàng của owner khác; `INSERT` owner trống trên `facts` bị `CheckViolation`.

## 12. Rollback

Không có migration xuống. Xóa một hàng `schema_migrations` không hoàn tác cột hay trigger; lần `apply` sau chỉ bỏ qua version đã ghi.

1. Dừng `python -m pu dashboard` và `python -m pu worker`.
2. SQLite: thay cả thư mục `PU_HOME` bằng bản copy ở mục 6. Đừng xóa tay bảng `*__pre_owner` khi 9005 đang dở. Mở lại để `_resume_interrupted` xử lý. Nếu nó báo bảng sống dài hơn backup, dừng và phục hồi cả file `state.db` từ bản copy.
3. Blob đã thành `enc2` chỉ trở lại `enc1` nếu phục hồi `state.db`. Khóa sai không giải được thì hàng ở `migration_pending = 1` và `use_oauth_connection` trả `None`. Đừng xóa `legacy_digest` để "chạy lại": digest là tập đã ghim, và blob `enc1` không khớp digest không được viết lại.
4. Xóa `owners/<id>/` không trả ownership SQL về trạng thái cũ. File gốc ở home vẫn còn vì mirror không xóa nguồn.
5. PostgreSQL chỉ cần phục hồi nếu bạn đã gọi `install` trên database đó. Ứng dụng đang chạy không giữ state ở đó. `install` với `replace_existing=False` từ chối khi schema còn hàng. `replace_existing=True` xóa schema `pu_phase1`.
6. Thu hồi phiên (`revoked_at`) không rollback dữ liệu. `reset_local_data` trong `pu/ops/reset.py` không phải rollback: nó xóa gần như cả home, giữ một danh sách file cấu hình, rồi `connect` tạo database mới. `pu/__main__.py` không gắn hàm này vào CLI.

## 13. Những gì đã đối chiếu và chưa có trong mã

Đã đọc và đối chiếu: `pyproject.toml`, `pu/config.py`, `pu/__main__.py`, `pu/db.py`, `pu/persistence/migrations.py`, `pu/persistence/ownership.py`, `pu/persistence/postgres_schema.py`, `pu/persistence/factory.py`, `pu/identity/crypto.py`, `pu/identity/session.py`, `pu/identity/files.py`, `pu/identity/directory.py`, `pu/identity/oidc.py`, `pu/identity/legacy_import.py`, `pu/ops/dashboard.py`, `pu/ops/telemetry.py`, `pu/ops/tracing.py`, tool Google, `Makefile`, và các test `PU_POSTGRES_DSN`.

Chưa có trong mã, nên hướng dẫn không bịa lệnh cho chúng:

- Process dashboard, CLI, worker hoặc `AuthStore` mở `PU_POSTGRES_DSN`. Factory trả SQLite. RLS/`pu_app` là hợp đồng test, chưa phải ranh giới đang sống.
- Lệnh migrate, backup, rollback, hoặc copy `knowledge/` / token / `calendar.ics` sang `owners/<id>/`.
- Map một `sub` OIDC sang user `identity_local`, nên đăng nhập trình duyệt không nhận dữ liệu home cũ.
- Bind khác `127.0.0.1`, cookie không `Secure`, hoặc `POST` chấp nhận `Origin` scheme `https`.
- Kiểm tra thuộc tính role `service_role` và `postgres` trên một project Supabase. Mục 5 chỉ áp ràng buộc `NOSUPERUSER` / `NOBYPASSRLS` của `install`, và chỉ cho lúc PostgreSQL được nối.
