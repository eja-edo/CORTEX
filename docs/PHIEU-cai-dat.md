# Phiếu: Cài đặt & khởi tạo (WP39–WP43)

Ngày lập: 2026-11-01 · Trạng thái: **Agent A đã xây WP39–43 + quên mật khẩu qua email (2026-11-02), chờ Agent B kiểm** · Lý do tồn tại: mọi bước khởi động doanh nghiệp (kênh, catalog, thông báo, giờ làm việc) hiện chỉ làm được bằng CLI, nên người ngoài không tự dùng và không tự demo được sản phẩm.

## 0. Luật L1 (AGENTS.md)

1. **Cổng / gói việc:** đưa vào đợt "sẵn sàng chạy thật" (DESIGN §7.2) và là điều kiện cho G1: chủ trung tâm phải tự thiết lập được mà không cần người vận hành gõ lệnh.
2. **Đưa tới cổng bằng cách nào:** gỡ các lệnh `create-connector`, `add-notify-target`, `import-catalog` ra khỏi đường bắt buộc của người dùng cuối.
3. **Bằng chứng trong `docs/customers/`:** **chưa có** (thư mục chỉ có mẫu). Ghi thẳng: gói này dựa vào việc người xây tự thấy CLI chặn việc giao sản phẩm, không dựa vào lời khách. Khi có phỏng vấn đầu tiên phải đối chiếu lại và cắt gói nào khách không nhắc.

Nhóm C (an toàn/pháp lý) vẫn bắt buộc trước khi chạm dữ liệu khách thật. Gói này chỉ chạy trên dữ liệu giả.

## 1. Cái gì làm, cái gì không

### Làm
| WP | Gói | Backend đã có để tái dùng | Việc mới |
|---|---|---|---|
| WP39 | **Trang Cài đặt có mục** (Doanh nghiệp · Kênh · Thông báo · AI · Google) | `Settings.tsx` hiện chỉ chứa `GoogleSection`; `Tenant.name/timezone`; `Sandbox.business_hours`; `killswitch.py` | Khung tab; `GET/PUT /settings/business` (tên, múi giờ, giờ làm việc); quyền `settings.manage` (chỉ chủ); nhật ký `settings.updated` |
| WP40 | **Thông báo** | `NotifyTarget`, `notify/service.py`, `cli add-notify-target` | `GET/POST/DELETE /settings/notify-targets`, nút "gửi thử"; địa chỉ webhook che khi hiển thị (R120) |
| WP41 | **Kênh** (Pancake/Messenger) | `Connector`, `cmd_create_connector` | Tạo/xoá connector, xem trạng thái (lần nhận tin cuối), hiện secret **một lần** như mật khẩu tạm ở Team |
| WP42 | **Catalog** | `CatalogItem`, `cmd_import_catalog`, validator A7 | Tải CSV lên, xem bảng, sửa/xoá dòng, báo dòng lỗi; mọi sửa ghi nhật ký |
| WP43 | **Onboarding + xoá dữ liệu một khách** | tất cả trên | Màn checklist 4 bước (kênh → catalog → bật skill → gửi thử) đọc trạng thái thật; `DELETE /customers/{id}` (xoá hội thoại, nháp, ký ức của một khách, để lại dòng nhật ký không chứa PII) |

Cài đặt AI (`send_policy`, tạm dừng) **không có gói riêng**: màn đã nằm ở `SandboxDetail` và `killswitch`; WP39 chỉ thêm liên kết/tóm tắt ở tab AI.

### Không làm (và vì sao). Ghi cả vào báo cáo đồ án, mục "hướng phát triển"
| Hạng mục | Lý do |
|---|---|
| Đăng ký tự phục vụ | Chưa có gói miễn phí/trả phí; DESIGN §2.2 bán có người hỗ trợ; chưa có khách; kéo theo xác minh email + chống spam + điều khoản |
| Thanh toán, hoá đơn | Chưa có giá; G1 đặt việc bán trước việc code |
| 2FA (R103) | Giá trị khi có dữ liệu khách thật; đồ án dùng dữ liệu giả |
| SSO Google/Facebook | Nhóm nhỏ, mật khẩu đủ |
| Quên mật khẩu qua email | Chưa có hạ tầng gửi thư; chủ có `cli reset-password`, nhân viên nhờ chủ |
| Responsive điện thoại (R85) | Chờ phỏng vấn xem nhân viên có dùng điện thoại không |
| Biểu đồ nâng cao, xuất Excel, đa ngôn ngữ, thêm kênh Zalo | Chưa có dữ liệu thật / khách / nền tảng |

## 2. Hai agent

### Agent A: Thiết kế & lập trình (`builder`)
- Làm theo thứ tự WP39 → 43, **mỗi gói một commit riêng** (để không lặp lại tình trạng 126 tệp chưa commit).
- Mỗi gói: (1) đọc `PLAN.md` §2/§9 và `console/` liên quan, (2) viết thiết kế ngắn (endpoint, quyền, bảng) vào mục 4 của phiếu này, (3) code backend, (4) code màn React theo mẫu `Team.tsx`/`Google.tsx`, (5) viết test pytest + vitest cho phần của mình, (6) ghi `REVIEW.md`.
- Quyền sửa: `cortex_leads/console/` (tệp mới `settings.py`, `channels.py`, `catalog.py`, `onboarding.py`), `auth/perms.py` (thêm quyền), `web/src/pages/`, `web/src/api/`, `cli.py` chỉ để giữ lệnh cũ chạy được. **Không** sửa `0001_initial.py`; cần bảng/cột thì thêm migration mới. **Không** đụng `guard/`, `tools/send.py`, `outbound/` (A7/A9).
- Dùng lại hàm nghiệp vụ có sẵn, không viết lại logic trong router.

### Agent B: Kiểm thử & đánh giá (`qa`), độc lập với A
- **Không sửa code sản phẩm.** Chỉ thêm tệp trong `tests/` và ghi báo cáo; thấy lỗi thì ghi vào `REVIEW.md` (mã R mới) và trả lại A.
- Chạy trên **DB riêng** (`createdb cortex_leads_qa`, `.venv/bin/python -m pytest`, không dùng `make test`; xem AGENTS.md, DB demo bị TRUNCATE).
- Việc B làm sau mỗi gói của A:
  1. **Bất biến:** `test_every_endpoint_has_been_given_a_decision` xanh; mọi endpoint mới có `need()`; A1 (tenant A không thấy catalog/kênh/thông báo của tenant B); A3 (tenant/actor lấy từ phiên, không từ body); mật khẩu/secret/token không lọt vào log, nhật ký, API.
  2. **Quy ước:** `tests/core/test_conventions.py` (cấm `isoformat`/`strftime`).
  3. **Kiểm thử đối kháng:** thiếu CSRF, vai `staff` gọi endpoint của chủ, CSV độc (công thức `=cmd`, dòng quá dài, mã hoá lạ, 100k dòng), webhook trỏ mạng nội bộ (SSRF), xoá khách đang có nháp chờ duyệt, giờ làm việc sai (`25:00`, giờ đóng trước giờ mở).
  4. **Giao diện:** `make web-test`; chụp ảnh từng màn bằng trình duyệt headless trên bản demo; duyệt chữ tiếng Việt, trạng thái rỗng/lỗi/đang tải.
  5. **Một lượt đi hết onboarding trên DB trống** bằng tay theo checklist, ghi thời gian và số lần phải xem tài liệu.
  6. Chạy `ruff` trên tệp đã đổi: **không thêm cảnh báo mới**.
- Đầu ra mỗi gói: bảng Đạt/Không đạt theo mẫu PLAN §6, danh sách lỗi theo mức, và quyết định **Cho qua / Trả lại**.

### Quy trình ghép
```
A: thiết kế gói k -> code + test của A -> commit -> báo "sẵn sàng"
B: kiểm theo mục trên -> Cho qua | Trả lại (kèm lỗi)
A: sửa lỗi -> B kiểm lại phần lỗi -> Cho qua
Chỉ khi Cho qua mới sang gói k+1. Hai agent không sửa cùng tệp cùng lúc.
```
Cuối đợt: B chạy **toàn bộ** `pytest` (chạy nền, quá 9 phút) + `web-test` và ghi số liệu vào mục 5.

## 3. Tiêu chí hoàn thành
- Người chưa từng thấy repo dựng được doanh nghiệp demo từ DB trống **chỉ bằng giao diện** (trừ bước tạo tenant đầu tiên), dưới 15 phút.
- Không còn lệnh CLI nào bắt buộc cho luồng "khách im → nháp → duyệt" ở demo.
- Toàn bộ test cũ vẫn xanh, thêm test cho mọi endpoint mới, ruff không tăng.
- Mỗi gói đã commit; `REVIEW.md` ghi hạn chế còn lại (đặc biệt: chưa kiểm với Pancake/LLM thật).

## 4. Thiết kế chi tiết từng gói (Agent A, 2026-11-02)

Chung: quyền mới `settings.manage` (chỉ chủ) trong `auth/perms.py`; router mới ở `console/` (`settings.py`, `recovery.py`, `customer_data.py`, `onboarding.py`) gắn vào `console/api.py`; tenant/actor lấy từ phiên (A3); mọi thay đổi ghi nhật ký (`audit`), không ghi secret/token/mật khẩu. Migration **0039** (`tenant.ai_name`, bảng `password_reset`).

### WP39 Hồ sơ doanh nghiệp: `GET/PUT /settings/business`
- Trường: `name` (2–80), `timezone` (kiểm bằng `ZoneInfo`), `hours.start/end` (`HH:MM`, đóng sau mở; ghi vào `sandbox.business_hours` của **mọi** sandbox của doanh nghiệp, vì `tools/send.next_open` đọc từ đó), `ai_name` (0–40 ký tự, chữ/số/khoảng trắng/`-'.`; rỗng = dùng tên doanh nghiệp).
- Dòng xưng AI (A9, Luật AI 134/2025) hiện do `tools/send.py` dựng `f"Trợ lý AI của {tenant.name}"`. `core/identity.py::ai_disclosure()` dựng dòng đó từ `ai_name`, **luôn bắt đầu bằng "Trợ lý AI"** nên không thể cấu hình thành tên giả làm người. **Chưa nối vào `send.py`** (tệp bị cấm sửa trong phiếu này): cần một dòng thay đổi do chủ dự án duyệt. Đã ghi REVIEW.
- Nhật ký `settings.updated` kèm diff từng trường.

### WP40 Thông báo: `GET/POST/DELETE /settings/notify-targets`, `POST …/{id}/test`
- `kind` telegram (chat id `-?\d{3,20}`) hoặc mezon (URL qua `egress.ensure_callable`: https, host trong danh sách cho phép, IP công khai). `sandbox_id` tuỳ chọn (phải thuộc doanh nghiệp).
- `cl_app` không có DELETE trên `notify_target` nên "xoá" = `active=false` (đích dừng nhận, hàng còn để nhật ký trỏ tới).
- Địa chỉ hiển thị che: telegram `…1234`; mezon `host/…`. Không bao giờ trả URL đầy đủ sau khi lưu (R120).
- Gửi thử dùng lại `notify.worker._send/_send_mezon`; telegram cần `CL_TELEGRAM_BOT_TOKEN`, thiếu thì báo `NOT_CONFIGURED`. Tin thử không chứa dữ liệu khách.

### WP41 Kênh: `GET/POST/DELETE /settings/channels`
- Tạo connector (`messenger`, `pancake`…, theo `sandbox_id` customer_care của doanh nghiệp), secret sinh bằng `secrets.token_urlsafe(32)`, mã hoá Fernet như `cmd_create_connector`, **trả về một lần** trong phản hồi POST. `connector` không có RLS, nên mọi truy vấn lọc `tenant_id` tường minh.
- Trạng thái: `last_event_at` từ `ingest_event.received_at` mới nhất; "xoá" = `status=disabled` (không có DELETE; tin cũ còn trỏ tới).
- Hướng dẫn nối bridge hiện `CL_INGEST_URL` từ `PUBLIC_BASE_URL`.

### Tab AI: `GET /settings/ai`
- Chỉ đọc, gom: mỗi sandbox customer_care (tên, `send_mode`, `status`), tổng quan `never_say`/`must_handoff` từ skill đang chạy, trạng thái tạm dừng. Đổi chế độ gửi và tạm dừng dùng lại endpoint sẵn có (`/sandboxes/{id}/send-mode`, `/kill-switch`); tab chỉ gọi lại chúng.

### Quên mật khẩu qua email
- Bảng `password_reset(id, tenant_id, user_id, token_hash, expires_at, used_at, created_at, ip)`; RLS FORCE + policy tra cứu đúng một dòng theo `app.reset_token` (băm của token), như `session_lookup`. Token = 32 byte ngẫu nhiên, DB chỉ giữ SHA-256. Hạn 30 phút, dùng một lần (claim bằng `UPDATE … WHERE used_at IS NULL`), yêu cầu mới vô hiệu hoá token cũ chưa dùng.
- `POST /auth/forgot` (công khai): luôn trả cùng một phản hồi. Phần có/không có tài khoản chạy **sau** phản hồi (BackgroundTasks) nên thời gian không lộ. Giới hạn: 3 thư/giờ cho một email, 10 yêu cầu/giờ cho một IP (dùng `auth/throttle.fail`); IP vượt giới hạn → 429 (không phụ thuộc email).
- `POST /auth/reset {token, password}` (công khai): luật mật khẩu của `auth/passwords`; thành công thì kết thúc mọi phiên, xoá bộ đếm khoá của tài khoản, nhật ký `password.reset_by_email`. Sai/hết hạn/đã dùng → cùng một lỗi `BAD_RESET_TOKEN`.
- `GET /auth/recovery` (công khai) → `{enabled}`; Login chỉ hiện "Quên mật khẩu?" khi bật.
- Thư: `notify/mailer.py` (SMTP `smtplib` + `ssl`; `CL_SMTP_*`, `CL_MAIL_FROM`; mailer bộ nhớ cho test; mailer tệp `CL_MAIL_DIR` cho dev). Liên kết dựng từ `CL_PUBLIC_BASE_URL` (không dùng Host của request), dạng `/app/reset#token=…`: token nằm ở **fragment**, không lọt vào log máy chủ hay header Referer. Thư không chứa mật khẩu.

### Xuất/xoá dữ liệu một khách: `GET /customers/{conversation_id}/export`, `POST /customers/{conversation_id}/erase`
- Quyền `settings.manage` (chỉ chủ): xoá dữ liệu cá nhân là quyết định pháp lý, không để nhân viên làm.
- **Ẩn danh hoá tại chỗ**, không `DELETE`: `cl_app` không có DELETE (và nới quyền là mở rộng bề mặt tấn công). Tin, nháp, `staff_action.edited_text`, `outbox.text`, `ingest_event.payload`, `contact_fact.value`, tên/SĐT/`external_id` của liên hệ và hội thoại bị thay bằng dấu xoá; khoá ngoài, số liệu và lịch sử trạng thái còn nguyên. `external_id` thành `erased:<uuid>` nên nếu khách nhắn lại sẽ là một liên hệ mới.
- Chặn (409 `PENDING_WORK`) khi còn `outbox` đang `queued/sending` hoặc nháp `proposed`/`approved`: nhân viên xử lý hoặc huỷ trước. Một transaction; nhật ký `customer.erased` không chứa PII (chỉ id nội bộ và số hàng).
- Hạn chế (ghi REVIEW): `audit_event` bất biến nên giữ nguyên (nhãn không chứa tên khách); bản tóm tắt tuần/tháng đã sinh (`digest`, `staff_task`) không bị quét.

### Onboarding: `GET /onboarding`
- Bốn bước, trạng thái đọc thật: kênh (có connector active), catalog (có dòng `catalog_item`), skill (có `skill_version` live/shadow trong sandbox customer_care), gửi thử (đã có hội thoại hoặc nháp). Mỗi bước kèm đường dẫn màn tương ứng. Catalog chưa có màn riêng: bước ghi "nhập bằng `cli import-catalog` hoặc màn catalog (sẽ có sau)".

## 5. Kết quả kiểm thử (Agent B, 2026-11-02)

Môi trường: Postgres 16 thật, DB riêng (`cortex_leads_qa`, `_qa2`, `_qa3`), LLM giả, không gửi mail thật. Không sửa code sản phẩm; theo `mtime`, không tệp nào trong `guard/`, `outbound/`, `tools/send.py`, `0001_initial.py` bị đổi trong đợt này (tệp A9 duy nhất đổi là `tests/e2e/test_walking_skeleton.py`, chỉ thêm các đường dẫn mới vào danh sách "đã biết").

### Số test thật
| Bộ | Kết quả |
|---|---|
| `tests/console` (gồm test của A) | **263 pass** |
| `tests/outbound`, `core`, `e2e`, `privacy`, `guard`, `db` | **173 pass** |
| Các thư mục còn lại (booking, bridges, cron, grader, lessons, llm, memory, notify, runner, sandbox, skills, staff_ui, tools, triggers…) | 556 pass, **3 fail** (`tests/cron`, R147: test phụ thuộc đồng hồ, không liên quan WP39-43) |
| Test do B thêm: `tests/console/test_qa_settings_wp39_43.py`, `tests/outbound/test_qa_r136_erase.py` (+ `tests/e2e` chạy lại) | **111 pass, 2 xfail có chủ đích** (R136, R143) |
| `vitest` | 207 pass / 20 tệp; `tsc -b` sạch; `vite build` sạch |
| `ruff` | Tệp A đổi: 1 cảnh báo `RUF012` ở `db/models.py` (lớp `Base`, có từ trước). Tệp test của B: sạch. Toàn repo 71 cảnh báo (R49 ghi 22, lần quét đầu phiên 57; phần tăng nằm ở test cũ, không phải tệp A đổi) |

### Bảng Đạt / Không đạt
| Mục kiểm | Kết quả |
|---|---|
| A1: 3 doanh nghiệp, kênh (`connector` không RLS), thông báo, hồ sơ, onboarding, xuất/xoá khách | **Đạt**: A không thấy, không sửa, không xoá của B/C; id của B trả 404 |
| A3: tenant/actor không lấy từ body | **Đạt**: `tenant_id` gửi kèm bị bỏ qua, connector mang tenant của phiên |
| Vai `staff` gọi 12 endpoint của chủ | **Đạt**: 403 hết; không phiên: 401 |
| Thiếu CSRF ở mọi thao tác ghi | **Đạt** |
| Giờ làm việc/múi giờ/tên xưng sai (24:00, 07:60, đóng ≤ mở, `UTC+7`, xuống dòng, link, quá dài) | **Đạt**: 422, không lưu gì |
| Webhook: 21 địa chỉ (127.0.0.1, 169.254.169.254, `[::1]`, `@`, cổng lạ, tên giả, `file:`, số thập phân/hex, DNS trả IP nội bộ hoặc lẫn) | **Đạt**: đều bị từ chối; địa chỉ không lộ ra API, nhật ký, log |
| Secret kênh hiện một lần | **Đạt**: không có ở lần đọc sau, `audit_event`, log, hay dạng rõ trong DB (quét mọi bảng); bản lưu giải mã đúng |
| Quên mật khẩu: cùng phản hồi từng byte (có tài khoản / lạ / bị khoá / 3 cách viết email / hết hạn mức) | **Đạt** |
| Quên mật khẩu: thời gian | **Đạt**: trung vị tới lúc có câu trả lời, 40 mẫu mỗi bên: **9,61 ms (có tài khoản) và 9,46 ms (không có)**; p90 10,59 / 10,34 ms |
| `/auth/reset`: token sai/hết hạn/đã dùng/thừa/thiếu ký tự | **Đạt**: cùng một phản hồi `400 BAD_RESET_TOKEN` (trừ token < 20 ký tự trả 422 vì kiểm độ dài, không nói gì về token thật) |
| Liên kết dựng từ `CL_PUBLIC_BASE_URL`, không từ `Host`/`X-Forwarded-Host`/`Origin` giả | **Đạt** |
| Token chỉ ở thư; DB chỉ có băm; không ở nhật ký/log | **Đạt** (quét toàn DB) |
| Dùng liên kết kết thúc mọi phiên; mật khẩu cũ hết dùng | **Đạt** |
| Mật khẩu yếu không tiêu liên kết | **Đạt** (nhưng xem R145) |
| Tài khoản bị khoá sau khi xin liên kết: không đặt lại được | **Đạt** |
| Một liên kết dùng song song 6 lần | **Đạt**: đúng 1 thành công, 5 bị từ chối (3/3 lần) |
| Yêu cầu mới vô hiệu liên kết cũ | **Đạt** |
| SMTP lỗi: khách không thấy gì, log không có địa chỉ | **Đạt** |
| Giới hạn tốc độ | **Đạt** (IP: 429 sau hạn mức; email: im lặng) |
| Yêu cầu *đầu tiên* đồng thời từ địa chỉ mới | **Không đạt**: HTTP 500, R143 |
| Xoá khách: quét toàn DB sau một lượt chạy runner thật | **Đạt**: 15 chỗ chứa dữ liệu cá nhân trước, **0** sau; xem R149 cho phần chưa quét được |
| Xoá khách: 409 khi đang gửi, không đổi gì, không ghi nhật ký xoá; cần `confirm: true`; dòng nhật ký xuất/xoá không có PII; outbox chưa gửi bị huỷ, khách bị chặn nhắn | **Đạt** |
| R136: tên xưng AI tới khách | **Không đạt (xác nhận)**: `tools/send.py:151` dựng `Trợ lý AI của {tenant.name}` bỏ qua `ai_name`. Màn Cài đặt hứa "Trợ lý AI Mai của …", khách nhận "Trợ lý AI của …". Hậu quả: lệch giữa màn hình và tin gửi; **không** mất dòng khai báo AI (vẫn có và vẫn nói là AI). Test `xfail(strict)` sẽ báo khi sửa |
| Giao diện (Chrome headless 1440px, 17 ảnh) | **Đạt có lỗi nhỏ**: 5 tab, đăng nhập → quên mật khẩu → thư → đặt lại, Onboarding, nút xoá có hộp xác nhận chạy đúng, không lỗi console. Lỗi trình bày: R146 |

### Quyết định theo gói
| Gói | Quyết định | Điều kiện |
|---|---|---|
| WP39 Hồ sơ doanh nghiệp | **Trả lại một phần** | R136: sửa một dòng ở `tools/send.py` (đường A9, cần chủ dự án duyệt) |
| WP40 Thông báo | **Cho qua** | R146(a) lỗi bố cục, R148 ghi nhận |
| WP41 Kênh | **Cho qua** | — |
| Tab AI | **Cho qua** | R146(c) |
| Quên mật khẩu qua email | **Cho qua có điều kiện** | Sửa R143 (500 khi đồng thời) trước khi mở cho người ngoài; chưa thử SMTP thật, SPF/DKIM (R140) |
| Xoá/xuất dữ liệu khách | **Cho qua** | R149: phần chưa quét; nhóm C |
| Onboarding | **Cho qua** | R142, R146(b)(e) |

### Chưa kiểm được
- **Gửi thư qua SMTP thật** (không có máy chủ; mailer chỉ thử với SMTP giả và thư mục tệp).
- **Telegram thật và Mezon thật** (nút "gửi thử"), Pancake/Messenger thật.
- **Điện thoại/màn hẹp**; tài khoản `staff` trong trình duyệt (đăng nhập tay trong kịch bản chụp ảnh không thành công; phần quyền được kiểm bằng API ở trên).
- Chưa chạy lại 3 test cron ở giờ khác để xác nhận R147.
- Tải: không đo ngoài 6 yêu cầu đồng thời.


### 5b. Giai đoạn 1: bỏ trùng lặp + màn Dữ liệu (Agent B, 2026-11-02)
| Hạng mục | Kết quả |
|---|---|
| A9: danh sách đường API trong test e2e | **Đạt**: chỉ thêm ba đường `/catalog`, `/catalog/template`, `/catalog/import`; phần kiểm "chỉ một đường gửi tin" và "thư viện mạng chỉ ở notify/outbound/llm/connectors/cells" không đổi |
| Phân quyền | **Đạt**: chưa đăng nhập 401; thiếu hoặc sai CSRF 403; nhân viên 403 cả khi `dry_run`, và `role` trong thân bị bỏ qua |
| A1/A3 | **Đạt**: `catalog_item` có RLS FORCE; ba doanh nghiệp, `tenant_id` trong thân không đổi gì, dữ liệu của B và C nguyên vẹn |
| Ngữ nghĩa nhập | **Đạt**: dry_run không ghi gì (đếm `catalog_item`, `audit_event` trước/sau); nhập hai lần = 0 thay đổi; đổi giá = phiên bản 2, dòng cũ `active=false`, không mất `attrs` (`suc_chua`); mục vắng trong tệp không bị tắt |
| A7 | **Đạt**: nháp viết với giá cũ, nhập giá mới, gửi bằng đường AI bị chặn `UNVERIFIED_CLAIM`, không có outbox; dòng cũ còn là lịch sử |
| Audit | **Đạt**: chỉ số đếm, không có tên hay số điện thoại của dòng |
| Nhập đồng thời cùng một mã | **Đạt**: hai yêu cầu cùng lúc không sập, còn đúng một dòng `active` |
| Tệp đối kháng (26 trường hợp + giới hạn) | **Không đạt 3 trường hợp**: R154 (ô > 131072 ký tự), R155 (`\r` đơn lẻ), R156 (`valid_until` gần năm 0001) đều trả 500. 23 trường hợp còn lại trả 200/422 sạch (NaN, Infinity, 1e999, 17 chữ số, âm, UTF-16, cp1258, NUL, BOM, SQL, tiêu đề đảo/thiếu/thừa/trùng, rỗng, 2000/2001/100.000 dòng, mã và tên quá dài, ô bắt đầu bằng `= + - @` lưu như chữ, mẫu CSV không xuất lại) |
| Giao diện (Chrome headless, 1440px, bản chạy thật) | **Đạt**: màn Dữ liệu khớp bản vẽ (4 ô thống kê, tìm kiếm, lọc, bảng); hộp thoại hai bước hiện đúng "2 mục mới / 1 dòng lỗi: Dòng 3 …"; Công cụ không còn tab Kênh; Sandbox → Chế độ gửi chỉ đọc kèm liên kết, Kênh & dữ liệu có liên kết sang Cài đặt và Dữ liệu; Kênh/Thông báo ẩn ô chọn sandbox khi chỉ có một; nhân viên thấy `/data` không có nút nhập, gõ `/settings` bị đưa về `/inbox` |
| Bật "Tự gửi" | **Đạt**: ở Cài đặt → AI bấm "Tự gửi" hiện hộp xác nhận (cảnh báo + "Bật tự gửi" / "Không"); không còn nút ghi nào ở Sandbox |
| Web vitest / tsc / build / ruff | 218/218 pass / sạch / sạch / test mới của B và tệp mới của A sạch (4 cảnh báo ruff còn lại là `tests/console/test_auth.py` có từ trước) |
| Ngoài quyền | **Không phát hiện**: `guard/`, `outbound/`, `tools/`, `migrations/` không bị sửa |

Lỗi theo mức: **Trung bình** R154, R155 (500 với tệp hợp lệ về kích thước; R155 gặp thật với CSV Mac). **Thấp** R156, R157, R158. Không có lỗi nghiêm trọng.

| Phần | Quyết định | Điều kiện |
|---|---|---|
| Bỏ trùng lặp giao diện (Công cụ, Sandbox, ô chọn sandbox) | **Cho qua** | — |
| Màn Dữ liệu và API catalog | **Cho qua có điều kiện** | Sửa R154, R155 (bắt `csv.Error`, một chỗ) trước khi cho người ngoài nhập tệp; R156, R157 sửa cùng lúc |
| Onboarding trỏ `/data` | **Cho qua** | — |

Chưa kiểm được: trạng thái rỗng của màn Dữ liệu trong trình duyệt (chỉ có vitest), mở tệp mẫu bằng Excel thật, giao diện điện thoại, hiệu năng bảng với 2000 dòng. Số test thật: `tests/console tests/core tests/e2e tests/outbound tests/bridges` **553 pass, 0 fail** (9 phút 53 giây, chạy trước khi thêm test của B); `tests/tools guard booking ingest db memory` **114 pass**; test của B (`test_qa_phase1_catalog.py`, `test_qa_phase1_a7.py`) **36 pass, 3 xfail có chủ đích** (R154, R155, R156). Chưa chạy: các thư mục `cells clock connectors cron domain grader lessons llm mcp_server notify privacy review runner sandbox skills staff_ui supervisor triggers` (phase 1 không chạm tới).


## 6. Giai đoạn 1 của việc đơn giản hoá cấu hình (2026-11-02)
Một việc, một nhà: bỏ chỗ trùng lặp trước, chưa đổi kiến trúc. Bản vẽ Pencil: khung 25 (Dữ liệu) và 26 (hộp thoại nhập CSV).
- **Bỏ trùng:** tab "Kênh" của Công cụ đã xoá (kênh chỉ sửa ở Cài đặt → Kênh nhắn tin). Sandbox → Chế độ gửi chuyển thành chỉ đọc kèm liên kết "Đổi ở Cài đặt → AI"; bước xác nhận khi bật tự gửi chuyển theo về Cài đặt → AI, nơi duy nhất còn ghi chế độ này. Sandbox → Kênh & dữ liệu có liên kết tới nơi quản lý kênh và thông báo, và tới màn Dữ liệu.
- **Ẩn khái niệm sandbox khi chỉ có một:** "Đưa tin vào" (Kênh) và "Nhận tin của" (Thông báo) chỉ hiện từ hai sandbox trở lên.
- **Màn Dữ liệu (`/data`, quyền `catalog.read` cho mọi người, `catalog.manage` chỉ chủ):** danh sách bảng giá và lịch học đang dùng (4 ô thống kê, tìm kiếm, lọc nhóm), tải tệp mẫu, nhập CSV hai bước (kiểm tra không ghi gì, rồi lưu). Logic nhập tách thành `cortex_leads/catalog/importer.py`, dùng chung với `cli import-catalog` và cầu nối Google Sheet. Bước "bảng giá" của màn Bắt đầu trỏ tới đây.
- **Chưa làm (giai đoạn 2-3):** trang Kết nối hợp nhất, bảng "Tình trạng hệ thống", gộp menu, mô hình mặc định + ghi đè. Hạn chế còn lại: REVIEW R150–R153.
