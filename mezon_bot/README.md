# mezon_bot — M0 (probe)

Chưa phải bot. Đây là **thí nghiệm phải chạy trước khi xây bot**, theo M0 trong `docs/mezon-bot-plan.md`.

## Vì sao có thư mục này

`MessageButtonClicked.extra_data` khai kiểu `string` trong SDK và **không có schema ở bất kỳ đâu** — không trong docs, không trong type. Mọi form ở R1 phụ thuộc vào việc parse chuỗi đó. Xây R1 trước nghĩa là viết parser cho một phỏng đoán. Thư mục này thay phỏng đoán bằng quan sát.

## Chạy

```bash
# Node 22 — KHÔNG phải 24, xem "Ràng buộc môi trường" bên dưới
nvm use 22
npm install

npm run dry-run          # không cần token — kiểm tra mọi thứ kiểm tra được offline

cp .env.example .env     # điền MEZON_BOT_ID + MEZON_BOT_TOKEN
npm run probe            # cần token — DM cho bot: *probe
```

Kết quả ghi vào `probe-findings.jsonl` (đã gitignore). **File đó mới là sản phẩm của M0**, không phải mã nguồn ở đây.

## Lệnh probe

| Lệnh | Trả lời câu hỏi nào |
|---|---|
| `*probe` | **`extra_data` thật chứa gì.** Form có đủ 7 input (text, textarea, number, select, radio đơn, radio nhiều, datepicker), mỗi loại đúng một lần, id riêng biệt ⇒ một lần bấm lộ ra cách cả 7 loại serialize, và ô bỏ trống có quay về không |
| `*stream` | Edit-as-you-go có chạy không, và tới nhịp nào thì gateway chặn (R3 sống chết ở đây) |
| `*dm` | `sendDM` có tự mở DM channel khi chưa có không (R4 cần gửi tới người chưa từng nhắn bot) |
| `*echo` | Message DM vào trông thế nào — phân biệt DM với channel ở đâu, text nằm ở trường nào |
| `*whoami` | Người gửi mang định danh gì ổn định, để làm `user_channels.address` |

## Đã xác minh (2026-08-17, không cần token)

- **`mezon-sdk@2.8.55`** — `.d.ts` được ship **khớp chính xác** source nhánh `master` đã đọc. Rủi ro "docs/source/package lệch nhau" ghi ở mục VII kế hoạch: **đã gỡ cho version này**. Pin đúng version trong `package.json`, đừng dùng `^`.
- `MezonClient`, `InteractiveBuilder`, `ButtonBuilder`, `EButtonMessageStyle`, `EMessageComponentType`, `Events` đều export thật từ package.
- `EMessageComponentType` = `{BUTTON:1, SELECT:2, INPUT:3, DATEPICKER:4, RADIO:5, ANIMATION:6, GRID:7}` — khớp source.
- Payload form dựng ra hợp lệ và serialize được: 7 field đều mang `inputs`, id không trùng, `max_options` đi đúng cho radio nhiều lựa chọn.
- **`defaultValue` đi được vào payload.** Đây là thứ chống đỡ cho luồng "AI trích task → trình form điền sẵn → user xác nhận" ở R1, khớp `TaskStatus.PENDING_CONFIRM` đã có.

## Đã sửa so với docs Mezon

- **`botId` là BẮT BUỘC.** `MezonClientCore` ném `"botId is required"` ngay trong constructor. Ví dụ `new MezonClient({ token })` trong `mezon-sdk-docs.md` không chạy được.
- `sendDM(content, code?, attachments?)` — docs ghi thiếu tham số thứ ba.
- Docs **không có** phần embed/button/form. Nguồn đúng là `packages/mezon-sdk/src/mezon-client/structures/InteractiveMessage.ts`.

## Ràng buộc môi trường (phát hiện khi cài)

`mezon-sdk` phụ thuộc `better-sqlite3@11.10.0` (native). Trên **Node 24 không có prebuilt binary**, và máy này không có `make` nên không build từ source được:

```
prebuild-install warn install No prebuilt binaries found (target=24.19.0 ...)
gyp ERR! stack Error: not found: make
```

**Node 22 cài sạch, không cần build tools.** Điều này phải vào Dockerfile khi triển khai: base image `node:22`, không phải `node:24`. Đây là ràng buộc thật, không phải chuyện máy dev — bất kỳ ai deploy trên Node 24 mà không có toolchain sẽ gặp đúng lỗi này.

## Sau khi chạy xong probe

Ghi kết quả vào mục VIII của `docs/mezon-bot-plan.md`, đặc biệt là hình dạng `extra_data`. M5 (lệnh + form) mở khoá từ đó.
