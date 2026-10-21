# AGENTS.md

> **Đọc [`docs/DESIGN.md`](docs/DESIGN.md) và [`docs/LESSONS.md`](docs/LESSONS.md) trước mọi task.** DESIGN.md là nguồn sự thật duy nhất: sản phẩm là gì, nguyên tắc, kiến trúc và kế hoạch. Tài liệu này chỉ mô tả *cách chạy code*, không mô tả *nên xây gì*.
>
> ⚠️ Trước mọi việc, áp **luật L1 trong DESIGN mục 0**:
> 1. Việc này thuộc cổng nào, hoặc gói việc v0 nào (§7.2)?
> 2. Nó đưa tới cổng đó bằng cách nào?
> 3. Bằng chứng nào trong `docs/customers/` cho thấy cần làm?
>
> **L3 đã bỏ ngày 2026-10-17:** code ngoài v0 được phép xây theo roadmap T1/T2, nhưng mỗi gói việc vẫn qua L1 và L7. **Trượt G1 (2026-10-23) thì dừng mọi code mới.** Nhóm C (an toàn/pháp lý) vẫn bắt buộc trước khi chạm dữ liệu khách thật.

## Repo này chứa gì

| Thư mục | Nội dung |
|---|---|
| [`cortex-leads/`](cortex-leads/) | **Dự án duy nhất.** Nền tảng v0 "không để rơi khách tiềm năng — AI đứng sau nhân viên tư vấn". **Trạng thái 2026-10-17:** đã xây tới WP26 (497 test, ≈ 7.990 dòng gồm bridge; L3 đã bỏ), mới chạy trên dữ liệu giả lập — chưa nối nền tảng thật (WP14), chưa có khách |
| [`docs/DESIGN.md`](docs/DESIGN.md) | Thiết kế bản 2.1, nguồn sự thật |
| [`docs/LESSONS.md`](docs/LESSONS.md) | Bài học đã trả giá: hướng đã chết, số đã đo, lỗi đã gặp |
| [`docs/customers/`](docs/customers/) | Bằng chứng từ người thật. **Chỉ bản ẩn danh**, vì repo này đang công khai |
| [`docs/LEGACY.md`](docs/LEGACY.md) | Hệ cũ đã gỡ ngày 2026-10-10: thứ gì còn đáng lấy lại từ git, ở commit nào |
| [`docs/archive/`](docs/archive/) | Kế hoạch và thiết kế cũ (bản 1). Chỉ để tra cứu, không làm theo |

Hệ cũ (`backend/`, `frontend/`, `mezon_bot/`, `workflow_service/`, `ocr_service/`, `stt_service/`, `infrastructure/`) **đã bị gỡ**. Không khôi phục chúng vào cây thư mục. Cần tham khảo thì dùng `git show 0a22e33:<đường dẫn>` (xem LEGACY.md).

## cortex-leads — cách chạy

Mọi lệnh chạy từ thư mục `cortex-leads/`.

```bash
make setup      # .venv (python3.12) + pip install -e .[dev]
make db-up      # Postgres 16 riêng của dự án, cổng host 5544
make migrate
make test       # pytest trên Postgres thật
```

Hướng dẫn chạy thử đầy đủ (tenant, connector, skill, bridge Pancake, MCP) nằm trong [`cortex-leads/README.md`](cortex-leads/README.md).

### Cách làm việc khi code

- **Hợp đồng xây dựng:** [`cortex-leads/PLAN.md`](cortex-leads/PLAN.md) chốt schema, kiểu chung, giao diện giữa các gói, và **quyền sở hữu tệp** của từng gói việc. Đọc nó trước khi sửa code.
- **Sổ review:** [`cortex-leads/REVIEW.md`](cortex-leads/REVIEW.md) ghi mọi phát hiện còn mở (R1, R2, …). Sửa xong một mục thì đánh dấu ✅ kèm ngày.
- **Đổi schema:** thêm revision Alembic mới. **Không sửa** `0001_initial.py`, vì nó dựng bằng `Base.metadata.create_all` từ models tại thời điểm đó.
- **Chạy test song song** (nhiều agent cùng lúc): mỗi agent dùng một DB riêng, nếu không test của người này sẽ TRUNCATE dữ liệu của người kia.
  ```bash
  docker compose exec -T pg createdb -U cl_owner cortex_leads_<tên>
  export CL_DATABASE_URL=postgresql+asyncpg://cl_app:cl_app_dev@localhost:5544/cortex_leads_<tên>
  export CL_DATABASE_OWNER_URL=postgresql+asyncpg://cl_owner:cl_owner_dev@localhost:5544/cortex_leads_<tên>
  ```
  Migration tự áp lên DB mới khi test chạy.
  ⚠️ Khi dùng DB riêng, chạy `.venv/bin/python -m pytest …` trực tiếp — **không** dùng `make test`, vì Makefile `source .env.test` sẽ ghi đè biến đã export và trỏ về DB chung (đã xảy ra, REVIEW R30).

### Bất biến — test phải giữ xanh

Chi tiết ở DESIGN §5.0.

| # | Bất biến |
|---|---|
| A1 | `tenant_id` + RLS (`FORCE`) trên mọi bảng dữ liệu. Code chạy bằng role `cl_app`, không phải owner |
| A3 | Tenant, actor, scope do server điền: lấy từ connector key, API key, hoặc `RunContext`. Không bao giờ lấy từ body hay tham số LLM |
| A7 | Validator chạy **bên trong** tool ghi. Mọi con số khách nhìn thấy phải trỏ về một dòng catalog |
| A9 | **Chỉ một đường gửi tin cho khách:** tool `send_message` → `outbox` → worker → bridge. Hai lớp chặn do người cấu hình: skill (`send_policy` auto/manual) và bridge (`outbound`). Chế độ manual không bao giờ sinh outbox khi chưa có người duyệt; AI chỉ gửi trong cửa sổ tự do, kèm dòng xưng AI |
| — | Dữ liệu cá nhân (tên, SĐT, email) được che trước mọi lời gọi LLM |

### Bẫy đã gặp

- **PyYAML đọc khoá `on` thành `True`** (YAML 1.1). Parse frontmatter skill **chỉ** qua `cortex_leads.skills.loader`, không gọi `yaml.safe_load` trực tiếp.
- **`mcp` là bản 2.x** (`mcp>=2,<3`). API khác bản 1.x: dùng `mcp.server.mcpserver.MCPServer`, không có `mcp.server.fastmcp`.
- **Owner trong Docker là superuser**, nên view bỏ qua RLS. View của supervisor dùng `security_invoker = true`.
- **Dòng cuối của prompt quyết định hình dạng JSON.** Dùng `cortex_leads.llm.shape.response_shape(example)` để *vẽ* shape bằng ví dụ, không chỉ nêu tên khoá.
- **`draft.created_at` dùng đồng hồ DB.** Test dùng `now` cố định thì phải dời dữ liệu seed về quá khứ thật.
- **Không dùng LLM endpoint không có DPA cho dữ liệu khách thật** (REVIEW R2, DESIGN §6). Ví dụ: 9Router `free_auto`.

## Bảo mật

- Repo đang **công khai**. Không commit secret, dữ liệu khách, catalog hay prompt riêng của khách. `cortex-leads/data/` và `.env*` (trừ `.env.test`) đã gitignore.
- `cortex-leads/.env.test` chỉ chứa giá trị **dành riêng cho test**. Config từ chối khởi động nếu secret trùng giá trị đã lộ của hệ cũ.
- Server EC2 cũ vẫn chạy hệ cũ từ nhánh `develop`. Xem DESIGN §10: vá bảo mật, dump DB, rồi tắt. **Không merge nhánh gỡ hệ cũ vào `develop` trước khi tắt server.**

## Codebase discovery

Index `codebase-memory-mcp` cũ (`home-duyanh-project-Cortex`) mô tả hệ đã bị gỡ, nên **không còn đúng**. Cần index lại (`index_repository`) trước khi dùng graph tools cho `cortex-leads`. Chưa index lại thì dùng Grep/Read.

## Agent Protocol

Before executing ANY task:

1. Read `.opencode/protocol.md` in full.
2. Read `.opencode/state/TASK.md`. That file, not the chat message, is the task.
3. Follow the mode contract in protocol.md section 1.
4. Write `.opencode/state/REPORT.md` using the template, and append to LOG.md.

`.opencode/protocol.md` takes priority over your default execution habits.
You are an executor, not a planner: never invent the next task, never widen scope.

> Ghi chú 2026-10-10: thư mục `.opencode/` hiện không tồn tại trong checkout này.
