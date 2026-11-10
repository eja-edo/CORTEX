# cortex-leads

AI đứng sau nhân viên tư vấn: không để rơi khách tiềm năng. Xem `../docs/DESIGN.md` (§5) và `PLAN.md`.

```bash
make setup     # venv + deps
make db-up     # Postgres 16 :5544 (roles cl_owner / cl_app / cl_supervisor) và Redis 7 :6390
make migrate   # alembic upgrade head (owner URL)
make test      # pytest (app role, RLS có hiệu lực)
```

Cấu hình: biến `CL_*` (xem `.env.test`). Đăng nhập console dùng access token JWT 15 phút cộng refresh token 7 ngày (`CL_ACCESS_TOKEN_MINUTES`, `CL_REFRESH_TOKEN_DAYS`, `CL_SESSION_ABSOLUTE_HOURS`); muốn thu hồi tức thì khi chạy **nhiều tiến trình** phải đặt `CL_REDIS_URL` (ví dụ `redis://localhost:6390/0`). Không đặt thì mỗi tiến trình tự nhớ trong bộ nhớ, chỉ hợp cho một tiến trình (phát triển, test). Redis chỉ giữ `user id → version` và chỉ là bộ đệm của DB, mất nó không làm mất việc đăng xuất. `CL_JWT_SECRET` để đổi khoá ký (không đặt thì suy ra từ `CL_CONNECTOR_SECRET_KEY`; đổi nó đăng xuất mọi người). Thiếu secret hoặc dùng secret đã lộ -> lỗi khi khởi động.

Quên mật khẩu qua email (tuỳ chọn, mặc định tắt): đặt `CL_PUBLIC_BASE_URL` (địa chỉ công khai của console) và một trong hai: `CL_SMTP_HOST` + `CL_MAIL_FROM` (kèm `CL_SMTP_PORT`, `CL_SMTP_USER`, `CL_SMTP_PASSWORD`, `CL_SMTP_STARTTLS`), hoặc `CL_MAIL_DIR` (phát triển: mỗi thư là một tệp trong thư mục đó, mở tệp lấy liên kết). `python -m dev.local setup` tự đặt `CL_MAIL_DIR=data/mail`. Hồ sơ doanh nghiệp, kênh, nơi nhận thông báo và chế độ gửi chỉnh trong console, mục **Cài đặt**; việc đầu tiên cần làm nằm ở **Bắt đầu**.

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
#    Trong giao diện: mục «Dữ liệu» (tải tệp mẫu, kiểm tra trước, rồi lưu). Lệnh dưới dùng cùng luật nhập:
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
python -m cortex_leads.cli ensure-sandboxes --tenant <T>   # doanh nghiệp tạo trước 2026-11-07; doanh nghiệp mới đã có sẵn mọi sandbox
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

### Tổng kết buổi học (sandbox `lesson_recap`, WP31)

Thả bản ghi buổi học vào một thư mục (Drive hoặc thư mục máy); Cortex chuyển thành chữ, viết tổng kết + bài tập về nhà, và đăng vào kênh Mezon của đội. Cần `ffmpeg`; chuyển chữ tại chỗ cần `pip install faster-whisper` (hoặc `CL_TRANSCRIBER=api` + `CL_WHISPER_API_KEY`, nhưng khi đó âm thanh rời máy: xem R117).

```bash
.venv/bin/python -m cortex_leads.cli create-sandbox --tenant $T --purpose lesson_recap   # đã có sẵn từ create-tenant: lệnh chỉ in sandbox_id
.venv/bin/python -m cortex_leads.cli add-lesson-source --tenant $T --sandbox $S --ref ~/bai-ghi   # thư mục trên máy, để thử; thư mục Drive nối ở console (Cài đặt → Kết nối Google)
.venv/bin/python -m cortex_leads.cli add-notify-target --tenant $T --kind mezon --chat-id https://<webhook của kênh>
.venv/bin/python -m cortex_leads.cli lessons           # vòng lặp riêng, --once để chạy một lượt
```

Địa chỉ webhook phải là `https`, host nằm trong `CL_WEBHOOK_ALLOW_HOSTS` (mặc định `webhook.mezon.ai`) và phân giải ra IP công cộng; để thử với Mezon giả trên máy, đặt `CL_WEBHOOK_ALLOW_LOCAL=true`. Muốn tải bản ghi lên từ console: nối một tài khoản Google ở **Cài đặt → Kết nối Google** (tick «Drive»), rồi tạo lớp ở trang **Buổi học**. Trang **Buổi học** có ô tải lên: chọn bản ghi, ngôn ngữ, bấm **Tải lên Drive**. Trình duyệt gửi tệp **thẳng lên Google Drive** (Cortex chỉ cấp phiên tải; khi chạy thật nên đặt `CL_PUBLIC_BASE_URL` đúng địa chỉ mở console (chạy local thì bỏ trống, Cortex dùng địa chỉ đang mở); hạn mức `CL_UPLOAD_PER_USER_DAY`/`CL_UPLOAD_PER_TENANT_DAY`). Tải lên **chỉ đưa tệp vào thư mục Drive**; từ đó vòng theo dõi tự nhặt, chuyển thành chữ và viết tổng kết, giống tệp thả tay vào thư mục (một đường xử lý duy nhất). Cortex không giữ bản ghi: trang phát lại bằng cách lấy tệp từ Drive (tệp tải lên tối đa `CL_UPLOAD_MAX_MB`, mặc định 1024). Cần vòng xử lý nền đang chạy (`cortex_leads.cli lessons`). Chỉ bản ghi từ thư mục tạo **sau khi** gắn nguồn mới được xử lý. Tổng kết chỉ gửi tới đích `mezon`, không bao giờ tới Telegram hay khách. Chưa thử với Mezon và Drive thật (R115, R116).

**Kết nối Google bằng giao diện (WP37).** Mục **Kết nối Google** trong **Cài đặt** (chỉ chủ) thay cho `classroom-login`, `add-classroom-source` và `add-drive-target`: bấm đăng nhập, chọn lớp Classroom hoặc nối Drive, không cần dòng lệnh. Một lần đăng nhập là một `google_account`; nhiều lớp và Drive cùng trỏ vào nó, và hai giáo viên nối hai tài khoản riêng. Ngắt một tài khoản thì mọi lớp và Drive dùng nó dừng, lịch sử giữ nguyên. Máy chủ cần một OAuth client loại *Web application* trong Google Cloud, với địa chỉ chuyển hướng `<địa chỉ console>/api/v1/google/callback`, rồi đặt `CL_GOOGLE_OAUTH_CLIENT_ID`, `CL_GOOGLE_OAUTH_CLIENT_SECRET` và `CL_PUBLIC_BASE_URL` (chỉ phần địa chỉ trang, không kèm `/app`). Drive nối từ giao diện **tự tạo thư mục riêng** trong Drive của giáo viên (quyền `drive.file`); muốn vòng theo dõi nhặt bản ghi từ đó thì chia sẻ thư mục ấy cho tài khoản dịch vụ đang theo dõi. **Lớp học (WP38).** Trang **Buổi học** có khung **Lớp học** (chỉ chủ): mỗi lớp là một thư mục Drive riêng (Cortex tạo trong Drive của giáo viên, hoặc một thư mục có sẵn chỉ để đọc) cùng một webhook Mezon riêng (tuỳ chọn). Tải lên chọn lớp; danh sách buổi học lọc được theo lớp; tổng kết của lớp chỉ gửi vào webhook của lớp đó (lớp không có webhook thì dùng kênh chung của sandbox, và kênh của một lớp không bao giờ nhận tin của lớp khác). Địa chỉ webhook là bí mật nên giao diện chỉ hiện tên máy chủ. Drive Targets đã bỏ (migration 0030).

**Không còn nguồn nối bằng khoá riêng:** các lệnh `classroom-login`, `add-classroom-source`, `add-drive-target` và đọc thư mục bằng tài khoản dịch vụ đã gỡ (migration 0029 tắt các nguồn cũ, giữ lịch sử). Mọi lớp, Drive và thư mục đều đi qua một tài khoản Google nối ở console.

### Chấm bài và giao bài trên Google Classroom (sandbox `classroom_grader`, WP33)

AI đọc bài nộp, **đề xuất** điểm theo thang điểm của giáo viên (mỗi tiêu chí kèm trích dẫn nguyên văn từ bài, được kiểm có thật); giáo viên xem và duyệt ở màn **Chấm bài**. Chỉ khi duyệt, điểm mới được lưu hoặc ghi lên Classroom, và **chỉ với bài do chính ứng dụng tạo** (Google không cho ghi điểm bài khác; bài giáo viên tạo tay chỉ được gợi ý điểm). Màn **Bài tập** soạn đề (tự soạn hoặc nhờ AI) rồi tạo trên Classroom sau khi duyệt, kèm thang điểm nên chấm được ngay.

Thử không cần tài khoản Google (Classroom giả có sẵn 3 học sinh, 2 bài tập):
```bash
.venv/bin/python -m dev.local.fake_classroom 8302 &
export CL_CLASSROOM_API_BASE=http://127.0.0.1:8302/v1 CL_GOOGLE_TOKEN_URL=http://127.0.0.1:8302/token
.venv/bin/python -m cortex_leads.cli create-sandbox --tenant $T --purpose classroom_grader   # đã có sẵn, như trên
# nối lớp: console, Cài đặt → Kết nối Google (không còn lệnh dòng lệnh)
.venv/bin/python -m cortex_leads.cli import-grading-guide --tenant $T --source $SRC --coursework-id w1 --file guide.yaml
.venv/bin/python -m cortex_leads.cli classroom --once     # chấm; vòng lặp: bỏ --once
```
`guide.yaml`: `title`, `max_points`, `criteria` (mỗi tiêu chí `id`, `label`, `points`, `descriptor`; **tổng điểm tiêu chí phải bằng `max_points`**), `answer_key` (tuỳ chọn). `check_prompt` (tuỳ chọn): lời giáo viên viết về **cách kiểm tra bài so với đáp án** (ví dụ chép chính tả: phải đủ các đoạn, đúng từng từ, bỏ qua dấu câu; bài của buổi khác thì 0 điểm), đưa nguyên văn cho AI khi chấm. Màn **Bài tập** có hai ô *Đáp án* và *Cách kiểm tra*. **Không có thang điểm thì bài không được chấm.**

**Thông báo:** mỗi bài nộp có đề xuất điểm gửi một tin vào kênh Mezon, mở đầu bằng dòng **Lớp: tên lớp** (tên khoá học trên Classroom, kèm phần nếu có), ghi rõ **học sinh, bài tập, điểm đề xuất theo từng tiêu chí, nguồn bài (PDF, bản ghi âm…), lưu ý**, trạng thái (**chưa phải điểm chính thức**: chưa duyệt, chưa ghi lên Classroom, học sinh chưa thấy điểm) và hai link: trang duyệt trong console (cần `CL_PUBLIC_BASE_URL`) và bài nộp trên Classroom. Link console mở thẳng bài đó (`/app/grading/<id>`, tự chuyển tới `/app/classes/<lớp>/assignments/<bài>?item=<id>`). Từ WP38 mọi thứ xoay quanh **Lớp học** (`class`): mỗi lớp có chế độ tổng kết (`recap_mode`: `auto`/`review`) và chế độ chấm (`grading_mode`: `manual`/`review`/`auto_write`), đổi ở "Sửa lớp"; mặc định `review`. Muốn tin chấm bài vào một kênh riêng: `add-notify-target --kind mezon --chat-id <webhook> --sandbox <id sandbox chấm bài>`; kênh gắn với sandbox thì thay cho kênh chung, và không nhận gì của sandbox khác.

**Định dạng bài nộp đọc được:** Google Docs, văn bản, PDF có chữ, Word (.docx), âm thanh và video (chỉ lấy tiếng, tối đa 15 phút, chép lời bằng Whisper như sandbox buổi học; cần `ffmpeg`). **Ảnh chụp (jpeg, png, webp)** chỉ đọc khi bật `CL_GRADER_SEND_IMAGES=true`: ảnh được gửi **nguyên bản** cho mô hình (tên trong ảnh không che được, xem REVIEW R134), mô hình chép lại chữ đọc được vào `transcript` (hiện ở màn Chấm bài, giáo viên đối chiếu với ảnh gốc) và chấm theo đáp án cùng `check_prompt`; trích dẫn chỉ được kiểm trên bản chép đó. Tắt công tắc thì ảnh bị bỏ qua như trước. PDF scan, slide chưa đọc được: bài được bỏ qua kèm lý do thay vì chấm một phần. Bài nói chỉ chấm theo **nội dung** (có bản chép lời), không chấm phát âm. Thử bài nói với Classroom giả: `python -m dev.local.fake_classroom 8302 --audio tiếng-nói.mp3`.

Nối Classroom thật: `--kind delegated` (service account hành động thay giáo viên `--subject`, cần quản trị miền cho phép uỷ quyền toàn miền) hoặc `--kind oauth` (client OAuth và refresh token của giáo viên). Chưa thử với Google thật (R124); bài và điểm học sinh thuộc nhóm C (R125): chỉ chạy dữ liệu giả hoặc lớp thử.

### Giao diện chính (console, WP27)

Giao diện cho chủ và nhân viên nằm ở `web/` (React + TypeScript + Vite + Tailwind), thiết kế ở `pencil/`. Cần Node 22+.

```bash
make web-install && make web-build         # bản build ở web/dist; chính API phục vụ nó ở http://localhost:8200/app/
make web-test                              # build (kiểm kiểu) + vitest
make web-dev                               # khi sửa giao diện: http://localhost:5173/app/, tự chuyển /api về :8200
```
Đăng nhập bằng API key (`create-api-key --role owner` cho chủ, `--role staff` cho nhân viên). Chủ thấy thêm: AI tổng, tạo sandbox, đổi trạng thái kỹ năng, **Dừng khẩn cấp**. Kill switch cũng có bản dòng lệnh: `python -m cortex_leads.cli pause --tenant <T> [--sandbox <S>]` / `resume`. API JSON ở `/api/v1` (xem `cortex_leads/console/`); mọi thao tác gọi lại đúng các hàm nghiệp vụ đã có, không có đường thi hành thứ hai. Chưa có màn Việc hôm nay, Dữ liệu, Báo cáo, Cài đặt (hiện là mục xám "Sắp có").

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

## Chọn tệp đính kèm từ Google Drive (WP45)

Nút **Chọn từ Google Drive** trong form soạn bài và form bài tập mẫu mở hộp thoại chọn tệp của Google (Google Picker) trên Drive của tài khoản Google đã nối. Máy chủ chỉ đưa cho trình duyệt một access token ngắn hạn thu hẹp còn `drive.file` (refresh token không rời máy chủ), nên cần bật một lần:

1. Google Cloud → dự án của `CL_GOOGLE_OAUTH_CLIENT_ID` → **APIs & Services → Library** → bật **Google Picker API**.
2. **Credentials → Create credentials → API key**; **Application restrictions: Websites** và thêm địa chỉ trang (vd. `https://cortex.example.vn/*`; khi chạy thử `http://localhost:5173/*`); **API restrictions: Google Picker API**.
3. Lấy **Project number** (Dashboard → Project info; số, không phải project id).
4. Đặt biến môi trường rồi chạy lại máy chủ:

```bash
export CL_GOOGLE_PICKER_API_KEY=<API key của bước 2>
export CL_GOOGLE_PROJECT_NUMBER=<project number của bước 3>
```

Địa chỉ trang cũng phải nằm trong **Authorized JavaScript origins** của OAuth client. Tài khoản Google đã nối từ trước phải có quyền Drive (`drive.file`); chưa có thì form báo và chủ trung tâm kết nối lại ở Cài đặt → Kết nối Google. Đây là cách duy nhất để đính kèm tệp vào bài tập hay bài tập mẫu (đã bỏ "Tải tệp từ máy" và "Dán địa chỉ" ở giao diện). Chưa đặt hai biến: nút tắt kèm lời giải thích và chưa đính kèm được tệp nào. Chưa kiểm trên Google thật.

## Nhật ký hoạt động (WP28)

Mọi đăng nhập (kể cả thất bại), đăng xuất, bị từ chối, và mọi việc người làm trong console được ghi vào `audit_event`
(IP, trình duyệt, mã yêu cầu, `metadata` JSON). Chủ xem ở `/app/audit` (lọc, phân trang, xuất CSV, "Kiểm tra toàn vẹn");
nhân viên chỉ xem dòng của mình. Kiểm chuỗi băm từ terminal: `python -m cortex_leads.cli audit-verify --tenant <uuid>`.
Đặt `CL_TRUST_PROXY_HEADERS=true` khi chạy sau reverse proxy để IP lấy từ `X-Forwarded-For`. Chi tiết: DESIGN §5.14.

## Kỹ năng, công cụ và nguồn dữ liệu (WP29)

- **Sửa kỹ năng tại chỗ:** `/app/skills/<id>/edit`. Form gốc được lưu (`skill_version.form_spec`), mỗi lần sửa ghi nội dung trước đó vào nhật ký và khôi phục được từ trang chi tiết. Kỹ năng đang bật/chạy thử chỉ chủ sửa.
- **Xoá là khoá:** kỹ năng từ form và nguồn dữ liệu chỉ bị ẩn và ngừng chạy; tab "Đã xoá" khôi phục được. Kỹ năng hệ thống không xoá được.
- **Công cụ & kết nối** (`/app/tools`, chỉ chủ): danh mục công cụ theo mức quyền, nguồn dữ liệu/MCP, kênh. Mỗi sandbox có ma trận "AI được dùng công cụ nào" ở `/app/sandboxes/<id>?tab=tools`; chủ tắt/bật công cụ theo sandbox.
- **Nguồn dữ liệu ngoài:** chỉ https, chỉ đọc, ghim cấu hình (và với MCP, định nghĩa công cụ). Định nghĩa đổi sau khi duyệt thì nguồn tự khoá cho tới khi chủ duyệt lại. Chỉ gắn được cho sandbox không nói chuyện với khách.

## Đăng nhập console (WP30)

Console đăng nhập bằng **email + mật khẩu**, không phải khoá API. Tạo tài khoản đầu tiên (chủ) bằng dòng lệnh, các nhân viên sau đó do chủ thêm ở `/app/team`:
```bash
python -m cortex_leads.cli create-user --tenant <uuid> --email chu@trungtam.vn --name "Chủ trung tâm" --role owner   # không --password: gửi thư mời (cần SMTP + PUBLIC_BASE_URL), người đó tự chọn mật khẩu; có --password: chủ đầu tiên của máy chủ chưa có thư
python -m cortex_leads.cli reset-mfa --email chu@trungtam.vn                                                      # chủ mất điện thoại và hết mã dự phòng: tắt xác thực 2 lớp, đăng xuất mọi thiết bị
python -m cortex_leads.cli reset-password --email chu@trungtam.vn                                                 # chủ quên mật khẩu và không nhận được thư: hỏi mật khẩu mới ở terminal (không in, không sinh)
```

**Vai trò** có ba: `owner`, `staff`, `teacher`. Giáo viên chỉ thấy các lớp chủ giao ở Nhân viên & quyền. Trong lớp đó họ xem và tải bản ghi, duyệt tổng kết, soạn, đăng, xoá bài tập, chấm bài, đổi tên lớp và chế độ tổng kết, chấm bài (trừ bật tự ghi điểm). Họ không có Hộp thư, kỹ năng, sandbox, dữ liệu; không đổi được kết nối Google, khoá học, webhook; không tạo, tắt, xoá lớp. Với nhiều lớp dùng chung một tài khoản Google, hộp chọn tệp của giáo viên chỉ có tab tải lên, xem giới hạn ở REVIEW R165.
`python -m dev.local setup` tạo sẵn một chủ và một nhân viên và in email + mật khẩu. Phiên hết sau 12 giờ hoặc 2 giờ không hoạt động; 5 lần sai khoá email 15 phút. Sau reverse proxy đặt `CL_TRUST_PROXY_HEADERS=true` để chống đoán theo địa chỉ đúng. Chi tiết: DESIGN §5.15.

## Trang quản trị nền tảng (WP47)

Dành cho **người vận hành máy chủ**, không phải chủ trung tâm: `/app/admin`. Trang này xem danh sách doanh nghiệp, tạo doanh nghiệp (đủ sandbox, chủ đầu tiên nhận thư mời), bổ sung sandbox thiếu, dừng hoặc chạy lại AI (một sandbox, một doanh nghiệp, hoặc mọi doanh nghiệp), và cứu tài khoản (gửi lại thư mời hoặc liên kết đặt lại mật khẩu, tắt xác thực 2 lớp, đăng xuất mọi thiết bị, mời thêm chủ). Trang không thấy khách, hội thoại hay mật khẩu của ai.

Tài khoản admin chỉ tạo được bằng dòng lệnh. Xác thực 2 lớp được cài ngay trong lệnh: dán khoá vào ứng dụng xác thực, nhập một mã để xác nhận, rồi cất 10 mã dự phòng:
```bash
python -m cortex_leads.cli create-admin --email ops@cortex.example.vn --name "Vận hành"   # hỏi mật khẩu (không in), cài TOTP, in mã dự phòng một lần
python -m cortex_leads.cli reset-admin-mfa --email ops@cortex.example.vn                  # admin mất điện thoại và hết mã dự phòng: khoá mới, phiên cũ kết thúc
```
Phiên hết sau 30 phút không hoạt động (`CL_ADMIN_IDLE_MINUTES`) hoặc 8 giờ (`CL_ADMIN_SESSION_HOURS`). Tắt 2 lớp của người khác và dừng mọi doanh nghiệp cần mã 6 số đang hiện. Tạo doanh nghiệp và mời chủ cần gửi được thư (`CL_SMTP_*` hoặc `CL_MAIL_DIR`, cùng `CL_PUBLIC_BASE_URL`); chưa có thư thì vẫn dùng `create-tenant` + `create-user --password`. Chi tiết: DESIGN §5.16.
