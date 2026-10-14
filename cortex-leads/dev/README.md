# Bộ chạy thử (DESIGN §5.12)

Chạy thử không tốn tiền trên laptop. Ba tầng: **giả lập** (CI, không mạng) -> **Twenty + Sheet thật** -> **Page thật** (`scenario_live.md`).

## 0. Chạy thử local bằng tay (không Facebook/Twenty/tunnel)
```bash
.venv/bin/python -m dev.local setup     # một lần; chạy lại = xoá và dựng lại DB `cortex_leads_local` (đổi tên: CL_LOCAL_DB)
.venv/bin/python -m dev.local serve     # lõi :8200 + Messenger giả :8300 + đồng hồ mỗi 20 giây; Ctrl+C để dừng
```
`setup` in URL trang nhân viên và staff API key (sinh vào `data/local.env`, gitignore). Mở `http://127.0.0.1:8300/`: tạo khách, nhắn "Khoá IELTS giá bao nhiêu ạ?" ("Gửi như khách"), bấm **Tua 25 giờ** rồi **Chạy đồng hồ ngay**; nháp hiện ở `/staff` (đăng nhập bằng staff key), bấm "Duyệt & gửi", tin về cửa sổ chat của khách (nhãn "Page gửi (qua Cortex)"). Tua **8 ngày** cho nháp ngoài kênh (không có gì tới `/actions`). "Trả lời như nhân viên" sinh echo hộp thư Page (không app_id). Không có `data/llm.env` thì dùng LLM giả; muốn LLM thật: sao `dev/local/llm.env.example` thành `data/llm.env`. Đổi cổng/thư mục data khi cần chạy song song: `CL_LOCAL_CORE_PORT`, `CL_LOCAL_CHANNEL_PORT`, `CL_LOCAL_DATA`.


**Dữ liệu mẫu:** `setup` nạp `dev/samples/trung_tam_mau.yaml` — một trung tâm Anh ngữ *giả lập* (9 khoá học, 8 mục thông tin: đăng ký, học thử, ưu đãi, hoàn phí, cơ sở, giáo viên, cam kết, học online). Đây cũng là **khuôn để thu dữ liệu của khách thật**: số đặt ở trường số riêng (validator chỉ cho AI nói số có ở đây), trường chữ tránh chữ số. Bản của khách thật để trong `data/`, không commit.

## 1. Giả lập (làm trước, không cần gì ngoài Postgres)
```bash
make db-up && make migrate            # hoặc dùng DB riêng qua CL_DATABASE_URL / CL_DATABASE_OWNER_URL
set -a; . ./.env.test; set +a
.venv/bin/python -m dev.scenario      # in từng bước bằng tiếng Việt, exit 1 nếu số liệu giám sát lộ chữ của khách
```
Các bước chưa có (WP8 gửi tin, WP9 trí nhớ, WP10 bridge Messenger) được ghi `TODO` ngay trong kết quả.

## 2. Facebook Page thử + Meta app (chế độ phát triển)
1. developers.facebook.com -> Create App (loại Business) -> thêm sản phẩm **Messenger**. Giữ app ở **Development mode**.
2. Tạo một Facebook Page thử; trong Messenger > API Setup, liên kết Page và sinh **Page access token**.
3. App roles > Roles: thêm tester (họ phải chấp nhận lời mời). Chỉ người có vai trò mới nhắn được; không cần App Review.
4. Lấy `App Secret` (Settings > Basic) và `App ID`.
5. Webhooks > Messenger: Callback URL = `https://<tunnel>/webhook` (bridge Messenger, WP10), Verify token tự đặt, đăng ký `messages`, `message_echoes`.

Env bridge Messenger (WP10): `MESSENGER_APP_SECRET`, `MESSENGER_VERIFY_TOKEN`, `MESSENGER_PAGE_TOKEN`, `MESSENGER_PAGE_ID`, `MESSENGER_OWN_APP_ID`, `CL_INGEST_URL`, `CL_CONNECTOR_ID`, `CL_CONNECTOR_SECRET`.

## 3. Đường hầm HTTPS
```bash
cloudflared tunnel --url http://localhost:8110   # bridge Messenger (MESSENGER_PORT, mặc định 8110); mở thêm một tunnel cho :8210 (bridge Twenty)
```
Dán URL `https://….trycloudflare.com/webhook` vào Meta / Twenty. URL đổi mỗi lần chạy -> cập nhật lại webhook.

## 4. Lõi
```bash
.venv/bin/python -m cortex_leads.cli create-tenant --name "Thu nghiem"      # in tenant_id, sandbox_id
.venv/bin/python -m cortex_leads.cli create-connector --tenant … --sandbox … --channel-kind messenger
.venv/bin/python -m cortex_leads.cli create-api-key --tenant … --role staff --staff-ref nv1
.venv/bin/python -m cortex_leads.cli sync-skills --tenant … --sandbox …
uvicorn --factory cortex_leads.app:create_app --port 8000
```
`CL_INGEST_URL=http://localhost:8000/ingest/v1/events`, `CL_CONNECTOR_ID`/`CL_CONNECTOR_SECRET` lấy từ `create-connector`.

## 5. Twenty CRM (Docker, bản gốc không fork)
```bash
cd dev/twenty && cp .env.example .env     # sửa ENCRYPTION_KEY, PG_DATABASE_PASSWORD
docker compose up -d                       # UI http://localhost:3000 ; kiểm cú pháp: docker compose config
```
`dev/twenty/docker-compose.yml` là bản nguyên văn của twentyhq/twenty (`packages/twenty-docker`); chỉ thêm `.env.example`. Cổng 3000 không trùng 5544/8000. Trong Twenty:
1. Settings > Data model > People: thêm trường text **`cortexRef`** (giá trị `<connector_id>:<external_id>`, vd `conn_abc…:psid_1001`). Khách không có ref thì bridge dùng SĐT của người liên hệ.
2. Settings > APIs & Webhooks > Webhooks: URL `https://<tunnel>/webhook`, object `opportunity` (created, updated). Sao chép **secret** của webhook.
3. Chạy bridge:
```bash
export TWENTY_WEBHOOK_SECRET=… CL_INGEST_URL=… CL_CONNECTOR_ID=… CL_CONNECTOR_SECRET=…
export TWENTY_STAGE_MAP='{"WON":"won","LOST":"lost","MEETING":"booked"}'   # theo tên stage trong Twenty
uvicorn --factory bridges.twenty.app:create_app --port 8210
```
Chữ ký: `X-Twenty-Webhook-Signature` = HMAC-SHA256 hex của `"{timestamp}:{body}"` (theo docs.twenty.com). **Giả định chưa xác minh trên Twenty thật:** đơn vị timestamp (giây hay ms - bridge nhận cả hai), và webhook kèm sẵn `data.pointOfContact` (nếu không, phải bật relation/gọi API Twenty -- sửa `map_event`).

## 6. Google Sheet mẫu
Import `dev/samples/catalog.csv` (cột `code,name,category,price,unit,valid_until`) và `orders.csv` (`ma_don,sdt_hoac_ref,trang_thai,gia_tri,ngay`) vào hai tab của một Sheet, chia sẻ "Anyone with the link: Viewer" (**chỉ dành cho dev**; khách thật dùng service account, T1). `gid` nằm trong URL của tab.
```bash
export GSHEET_ID=… GSHEET_CATALOG_GID=0 GSHEET_ORDERS_GID=… CL_TENANT_ID=… CL_INGEST_URL=… CL_CONNECTOR_ID=… CL_CONNECTOR_SECRET=…
.venv/bin/python -m bridges.gsheet.sheet --loop 300     # bỏ --loop để chạy một lần
```
`trang_thai`: `booked|won|lost|cancelled` (hoặc `đặt lịch|đã chốt|mất|hủy`). Gửi lại cùng `ma_don` + trạng thái là no-op; đổi trạng thái là sự kiện mới.
