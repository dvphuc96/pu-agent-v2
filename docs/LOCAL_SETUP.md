# Hướng dẫn cài đặt và chạy PU Agent

## 1. Điều kiện môi trường

Source yêu cầu Python **3.11 trở lên**.

Trên máy hiện tại:

- `python3`: 3.9.6 — không dùng lệnh này.
- `python`: 3.14.7 — dùng được.

Kiểm tra lại:

```bash
python --version
```

## 2. Tạo virtual environment và cài dependency

```bash
cd /Users/dvphuc/dev/project/protonx-class/pu-agent-v2

python -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e '.[sources,gmail,gcal,drive,pdf,tracing,dev]'
```

Mỗi lần mở terminal mới, kích hoạt lại môi trường:

```bash
cd /Users/dvphuc/dev/project/protonx-class/pu-agent-v2
source .venv/bin/activate
```

## 3. Cấu hình `.env`

Repo hiện đã có file `.env`. Không chép đè file này nếu đang có cấu hình hoặc API key cần giữ.

Nếu cài mới hoàn toàn:

```bash
cp .env.example .env
```

Các biến model cơ bản:

```env
PU_PROVIDER=openrouter
OPENROUTER_API_KEY=...
PU_MODEL=...
PU_SMALL_MODEL=...
TAVILY_API_KEY=...
```

Có thể chọn các provider sau:

| Provider | `PU_PROVIDER` | API key |
|---|---|---|
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai` | `OPENAI_API_KEY` |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` |
| GLM / Z.AI | `glm` | `ZAI_API_KEY` |
| Gemini | `gemini` | `GEMINI_API_KEY` |

Kiểm tra cấu hình:

```bash
python -m pu connections
```

## 4. Kết nối Gmail và Google Calendar

Gmail cần OAuth Desktop client tại:

```text
.pu/credentials.json
```

Cần bật Gmail API và Calendar API trong Google Cloud project. Sau đó kết nối Gmail:

```bash
python -m pu connect gmail
```

Calendar có thể kết nối trong Dashboard, mục **Connections**.

Các kết nối Gmail/Calendar trong ChatGPT không tự chuyển sang ứng dụng local này.

## 5. Chạy ứng dụng

Chat trên terminal:

```bash
python -m pu
```

Dashboard web:

```bash
python -m pu dashboard
```

Mở trình duyệt tại:

```text
http://localhost:9000
```

Tạo briefing thủ công:

```bash
python -m pu brief
```

Chạy worker tự động kiểm tra Gmail:

```bash
python -m pu worker
```

Có thể dùng Makefile thay cho các lệnh trên:

```bash
make run
make dashboard
make brief
```

## 6. AgentOps, tracing và Grafana

Khởi động stack quan sát:

```bash
docker compose -f observability/docker-compose.yml up -d
```

Nếu muốn xuất trace sang OpenTelemetry Collector, chạy Dashboard với:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 python -m pu dashboard
```

Các địa chỉ:

- PU Dashboard: http://localhost:9000
- Grafana: http://localhost:3000
- Prometheus: http://localhost:9090
- Tempo API: http://localhost:3200

Dừng stack:

```bash
docker compose -f observability/docker-compose.yml down
```

## 7. Kiểm thử và lint

Chạy deterministic tests:

```bash
python -m pytest -q evals/deterministic
```

Kiểm tra file `.env.example` được sinh đúng:

```bash
python scripts/generate_env_example.py --check
```

Chạy lint:

```bash
python -m ruff check pu evals scripts
```

Hoặc dùng Makefile:

```bash
make eval
make lint
```

## 8. Một số lỗi thường gặp

### Dùng nhầm Python 3.9

Nếu gặp lỗi package yêu cầu Python 3.11 trở lên, kiểm tra:

```bash
which python
python --version
```

Sau đó tạo lại virtual environment bằng Python 3.11, 3.12 hoặc 3.14.

### Gmail báo thiếu dependency

Cài lại với Gmail extra:

```bash
python -m pip install -e '.[gmail]'
```

### Dashboard hiển thị code cũ

Dừng process Dashboard rồi chạy lại. Backend Python không tự reload sau khi source thay đổi.

### Không có API key

Chạy:

```bash
python -m pu connections
```

Sau đó điền provider, API key và model tương ứng trong `.env`, hoặc cấu hình trong Dashboard.

### Reset dữ liệu local

Chỉ reset sau khi đã dừng Dashboard và Worker. Lệnh reset sẽ xóa database, memory, knowledge, reports, chat history và approvals local; không xóa email hoặc lịch trên Google.

