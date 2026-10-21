# cortex-leads

AI đứng sau nhân viên tư vấn: không để rơi khách tiềm năng. Xem `../docs/DESIGN.md` (§5) và `PLAN.md`.

```bash
make setup     # venv + deps
make db-up     # Postgres 16 :5544 (roles cl_owner / cl_app / cl_supervisor)
make migrate   # alembic upgrade head (owner URL)
make test      # pytest (app role, RLS có hiệu lực)
```

Cấu hình: biến `CL_*` (xem `.env.test`). Thiếu secret hoặc dùng secret đã lộ -> lỗi khi khởi động.

## Chạy thử v0

Chuỗi đầy đủ đã được chứng minh bằng `tests/e2e/test_walking_skeleton.py` (Postgres thật, LLM giả, không mạng).

> **Cảnh báo dữ liệu khách thật.**
> - **Không** trỏ `CL_LLM_BASE_URL` tới endpoint LLM không có thoả thuận xử lý dữ liệu (DPA) khi chạy với tin nhắn khách thật (REVIEW R2). Hệ thống đã che SĐT/email/tên trước khi gọi mô hình, nhưng đó chỉ là lớp giảm thiểu, không thay cho DPA.
> - Repo này **đang công khai**. Thư mục `data/` (token Pancake, cursor, CSV catalog thật) không bao giờ được commit; `.env` cũng vậy.
> - Bridge Pancake chỉ **GET** từ Pancake; không có đường nào để hệ thống nhắn khách. Nhân viên tự gửi, rồi bấm "sent" trong API duyệt nháp.

Muốn tự bấm thử cả luồng trên laptop (khách giả + trang nhân viên, không cần Facebook): xem `dev/README.md` mục 0 (`python -m dev.local setup` rồi `serve`).

Các lệnh dưới chạy từ thư mục `cortex-leads/`. Cần biến `CL_*` (xem `.env.test` làm mẫu; `CL_CONNECTOR_SECRET_KEY` là khoá Fernet, không dùng giá trị mẫu cho môi trường thật).

```bash
# 1. Cài đặt, Postgres, migrate
make setup && make db-up && make migrate
set -a; . ./.env.test; set +a            # hoặc file .env của bạn (đừng commit)
PY=.venv/bin/python

# 2. Tenant (kèm sandbox customer_care), connector, API key
$PY -m cortex_leads.cli create-tenant --name "Trung tam ABC"      # in tenant_id, sandbox_id
$PY -m cortex_leads.cli create-connector --tenant $TENANT --sandbox $SANDBOX --channel-kind messenger
                                                                    # in connector_id + secret (chỉ hiện 1 lần)
$PY -m cortex_leads.cli create-api-key --tenant $TENANT --role staff --staff-ref nv1
$PY -m cortex_leads.cli create-api-key --tenant $TENANT --role supervisor   # chỉ xem số liệu, không thấy văn bản

# 3. Skill: đồng bộ từ sandboxes/customer_care/skills, rồi bật draft -> shadow -> live
$PY -m cortex_leads.cli sync-skills --tenant $TENANT --sandbox $SANDBOX
$PY - <<PYEOF   # CLI chưa có lệnh promote: gọi thẳng registry
import asyncio
from uuid import UUID
from cortex_leads.db.session import tenant_session
from cortex_leads.skills.registry import promote

async def main():
    t, sb = UUID("$TENANT"), UUID("$SANDBOX")
    async with tenant_session(t) as s:
        for name in ("hoi-lai-khach-im", "hoi-lai-dung-hen"):
            await promote(s, sb, name, 1, "shadow")
            await promote(s, sb, name, 1, "live")
asyncio.run(main())
PYEOF

# 4. Catalog (CSV: code,name,category,price,unit,valid_until). Giá trong nháp chỉ lấy từ đây.
$PY -m cortex_leads.cli import-catalog data/catalog.csv --tenant $TENANT

# 5. API (ingest + duyệt nháp + supervisor)
$PY -m uvicorn cortex_leads.app:create_app --factory --port 8200

# 6. Bridge Pancake (poll, chỉ GET) -> POST có ký HMAC vào /ingest/v1/events
export PANCAKE_PAGE_ID=... PANCAKE_PAGE_TOKEN=...      # hoặc đặt token vào data/pancake_page_token
export CL_INGEST_URL=http://localhost:8200/ingest/v1/events
export CL_CONNECTOR_ID=<connector_id> CL_CONNECTOR_SECRET=<secret>
# tuỳ chọn: PANCAKE_CHANNEL_KIND=messenger (mặc định)
$PY -m bridges.pancake.run                 # một lần; thêm --loop 60 để poll mỗi 60 giây
                                            # lần đầu backfill 7 ngày; cursor ở data/pancake_cursor.json

# 7. Đồng hồ im lặng + chạy job (cần CL_LLM_* hợp lệ, xem cảnh báo DPA ở trên)
$PY -m cortex_leads.cli sweep              # khách im >= 24h -> tạo job (không tốn token)
$PY -m cortex_leads.cli run-pending        # chọn top-K mỗi nhân viên rồi mới gọi LLM
# hoặc gộp: cli sweep --run ; đặt vào cron mỗi 10-15 phút

# 8. Xem và xử lý nháp bằng API (đúng người đã gõ tay gửi mới bấm "sent")
curl -H "X-Api-Key: $STAFF_KEY" localhost:8200/review/drafts
curl -X POST -H "X-Api-Key: $STAFF_KEY" -H 'Content-Type: application/json' \
     -d '{"action":"sent"}' localhost:8200/review/drafts/<draft_id>/action   # sent|edited|self|skipped
curl -H "X-Api-Key: $SUP_KEY" localhost:8200/supervisor/summary
```

Nháp mà khách đã nhắn lại sau đó sẽ `expired`, bấm `sent` trả 409 `STALE`. Trường `window.basis = "human_agent"` nghĩa là đã quá cửa sổ 24h tự do của Messenger: chỉ người gõ tay mới được gửi (REVIEW R6/R15).

### Thông báo đẩy cho nhân viên (WP17)

```bash
export CL_TELEGRAM_BOT_TOKEN=...            # bot tạo bằng @BotFather
export CL_PUBLIC_BASE_URL=https://cortex.example.vn
python -m cortex_leads.cli add-notify-target --tenant <T> --chat-id <chat id của nhân viên hoặc nhóm>
```
`worker` đẩy một tin cho mỗi loại việc (khách chờ người, lịch học thử mới). Tin không có tên, SĐT hay nội dung khách, chỉ số lượng và link `/staff`.

### Lịch học thử (WP18)

Mỗi slot là một dòng catalog `category=lich_hoc_thu`: `valid_until` = giờ bắt đầu, `attrs.ngay` (dd/mm), `attrs.gio` (hh:mm), `attrs.suc_chua` (số chỗ). Skill `tra-loi-khach` v16 gọi `list_open_slots`, khách chọn thì `book` và hệ thống giữ chỗ trước khi tin xác nhận được soạn. Phiếu đăng ký online là dòng catalog `TT-PHIEU` (`attrs.url`); mọi đường dẫn trong tin gửi khách phải nằm trên một dòng catalog.

### Việc theo giờ và báo cáo tuần (WP19)

`worker` chạy `cron` mỗi lượt: 07:45 mỗi ngày danh sách khách chưa được trả lời (hiện ở đầu `/staff`, nút "Xong"), thứ Hai 08:00 báo cáo tuần (cần sandbox `owner_digest`):

```bash
python -m cortex_leads.cli create-sandbox --tenant <T> --purpose owner_digest
python -m cortex_leads.cli cron          # chạy tay một lượt
```
Báo cáo xem ở `/staff/digest` bằng API key role `owner`. Chỉ có số, không có chữ của khách.

### AI tổng (WP21)

Doanh nghiệp có sandbox `owner_digest` thì mỗi sáng AI tổng quét số liệu (không đọc tin nhắn) và mở **đề xuất** nếu thấy: nháp bị chặn nhiều, kỹ năng lỗi liên tiếp, nhân viên bỏ phần lớn nháp, gửi tin hay thất bại. Chủ (API key role `owner`) xem ở `/staff/proposals` và bấm quyết; AI tổng không tự đổi gì. Khi nhân viên bỏ phần lớn nháp, đề xuất là một **thẻ chiến lược**: đổi đúng một trường của kỹ năng (vd. số lần nhắn tối đa 3 → 2); duyệt thì sinh một bản thử, bản đang chạy giữ nguyên. `python -m cortex_leads.cli cron --llm` (và `worker`) thêm đoạn tóm tắt tuần do LLM viết từ các con số.

### Kỹ năng tự tạo bằng form (WP22)

Chủ (role `owner`) vào `/staff/skills`, chọn mẫu ("hỏi lại khách im" hoặc "nhắc đúng hẹn"), điền cách làm bằng lời của doanh nghiệp. Kỹ năng đi qua ba bước: bản nháp → **chạy thử** (viết nháp trên tin thật nhưng không ai được nhắn, không gửi gì; chủ đọc ở "Đọc bản nháp thử") → **bật** (cần ≥ 10 lượt thử). Kỹ năng tạo từ form chỉ soạn nháp cho nhân viên, không bao giờ tự gửi.

### Nhiều cell (WP26)

Mỗi cell là một bản đầy đủ (DB + worker riêng), khai bằng `CL_CELL` (mặc định `c1`). Connector tạo từ CLI của cell nào thì mang tên cell đó. Bridge chỉ có một địa chỉ ingest nên đi qua router, không có DB hay secret:

```bash
CL_CELLS='{"c1": "http://10.0.0.1:8100", "c2": "http://10.0.0.2:8100"}' \
  uvicorn cortex_leads.cells.router:create_app --factory --port 8000
```
Nhân viên và chủ vào thẳng cell của mình (mỗi cell một tên miền). Cell nhận nhầm connector của cell khác trả 421.

### Đánh dấu trên nền tảng (WP24)

Muốn hệ thống gắn nhãn/ghi chú ở nơi nhân viên làm việc, thêm vào `connector.outbound`: `"capabilities": ["send_message", "add_tag", "add_note"]`, `"tags": {"handoff": "AI: cần người"}`, `"notes": {"booking": "AI đã giữ chỗ học thử"}`. Sự kiện: `booking`, `handoff`, `won`, `lost`. Bridge Messenger không có nhãn nên trả `NOT_SUPPORTED`; cần một bridge cho nền tảng có API nhãn/ghi chú đã xác minh.

### MCP ngoài chỉ đọc (WP23)

```bash
python -m cortex_leads.cli add-mcp-connector --tenant <T> --sandbox <S> --name kho \
  --url https://mcp.example.vn/mcp --allow-host mcp.example.vn            # liệt kê tool của server
python -m cortex_leads.cli add-mcp-connector ... --tool get_stock           # ghim đúng định nghĩa đã đọc
```
Server đổi định nghĩa tool sau khi ghim thì connector từ chối chạy. Sau khi một lượt chạy đọc dữ liệu ngoài, lượt đó không được ghi gì nữa.

### Nguồn dữ liệu ngoài chỉ-đọc (WP20)

```bash
python -m cortex_leads.cli add-http-connector --tenant <T> --sandbox <S> --name kho \
  --url 'https://api.example.vn/v1/stock?sku={q}' --allow-host api.example.vn --secret <token>
```
Tool `external_lookup` đọc nguồn này cho các lượt chạy nội bộ; lượt chạy với khách không bao giờ được dùng (kết quả là dữ liệu không đáng tin).

### Gắn MCP (chỉ đọc) vào Claude Desktop

Máy chủ MCP chỉ có 4 công cụ đọc (`list_dropped_leads`, `read_conversation`, `lookup_catalog`, `list_drafts`), SĐT/email/tên đã che. Thêm vào `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cortex-leads": {
      "command": "/đường/dẫn/cortex-leads/.venv/bin/python",
      "args": ["-m", "cortex_leads.mcp_server"],
      "env": {
        "CL_DATABASE_URL": "postgresql+asyncpg://cl_app:...@localhost:5544/cortex_leads",
        "CL_DATABASE_OWNER_URL": "...",
        "CL_CONNECTOR_SECRET_KEY": "...",
        "CL_LLM_BASE_URL": "...", "CL_LLM_API_KEY": "...", "CL_LLM_MODEL_LITE": "...",
        "CL_MCP_TENANT_ID": "<tenant_id>",
        "CL_MCP_SANDBOX_ID": "<sandbox_id>"
      }
    }
  }
}
```

Sau `pip install -e .` các lệnh `python -m bridges.pancake.run` và `python -m cortex_leads.*` chạy được từ mọi thư mục (nhưng `data/` là đường dẫn tương đối theo cwd).
