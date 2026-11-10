# Cortex — Thiết Kế Hệ Thống

**Bản 2.1 · chốt 2026-10-10 · Nguồn sự thật duy nhất**

| Ngày | Thay đổi | Bằng chứng / lý do |
|---|---|---|
| 2026-10-09 | Khép bản 1 (Attention Gate nhắc việc nội bộ) và nhánh AI companion. Chốt hướng "không để rơi khách tiềm năng — AI đứng sau nhân viên tư vấn" | Hai vòng phản biện, 11 góc chuyên gia (tóm tắt ở [`LESSONS.md`](LESSONS.md)) |
| 2026-10-10 | Chốt kiến trúc 4 lớp, mô hình agent và cách ly, danh mục năng lực, MCP, hiệu năng | Vòng phản biện 3 (6 góc) |
| 2026-10-10 | **Tầm nhìn nền tảng:** nhiều sandbox / agent cho nhiều việc của chủ doanh nghiệp, có AI tổng giám sát (không đọc nội dung), trigger theo thời gian, Skill / MCP / kênh thêm theo quy ước chung không sửa code lõi, cổng nhận chuẩn cho bridge bên ngoài. Thêm §5.2, §5.6–5.8, cổng G2.5 | Vòng phản biện 4 (5 góc): 5/5 đồng ý tầm nhìn là **bản vẽ đích**, nền tảng phải được **rút ra từ việc thật** |
| 2026-10-10 | **Chủ dự án quyết định xây nền tảng tối thiểu (v0) ngay**, trước G2, trong thư mục mới `cortex-leads/`. L3 được sửa (xem §0) kèm ngân sách cứng và mốc giết. **Ghi lại để trung thực:** cả bốn vòng hội đồng khuyên không xây trước G2. Quyết định này chịu rủi ro đó có chủ đích | Quyết định của chủ dự án. Chưa có bằng chứng từ khách |
| 2026-10-10 | v0 xây xong (175 test). **Gỡ toàn bộ hệ cũ khỏi repo** theo quyết định của chủ dự án; file ngoài git (venv, `.env`, log, dữ liệu MinIO, `unsearch`) xoá vĩnh viễn. Danh sách thứ đáng lấy lại từ git ở [`LEGACY.md`](LEGACY.md) | Quyết định của chủ dự án; `cortex-leads` không phụ thuộc code cũ (đã kiểm) |
| 2026-10-10 | **AI có năng lực chủ động gửi tin cho khách** (A9, N1, N3, N4 sửa; §5.2 thêm chiều ra *Cortex Action Format*; §5.8 thêm `send_policy` và `outbound`). Muốn chặn thì chặn ở **hai lớp do người cấu hình**: skill (`send_policy`) và bridge — tầng giao tiếp giữa hệ thống và nền tảng (`outbound`). Mặc định vẫn là nháp | Quyết định của chủ dự án |
| 2026-10-12 | **Đầu ra của v0 = chạy thật được.** Mọi phần cần để chạy thật đều vào v0: trí nhớ và vòng đời lời hẹn (WP9), domain pack, bridge Messenger (WP10), bộ chạy thử và bridge Twenty (WP11), hai chế độ gửi **auto / manual** (WP8), trang duyệt cho nhân viên (WP13). **Ngân sách L3 nới từ 4.000 lên 5.000 dòng.** v0 có tiêu chí nghiệm thu A–D (§7.2). Mặc định *có thể đổi*: doanh nghiệp mới ở `manual`; skill "khách im" bắn ở mốc 20 giờ, trước khi cửa sổ 24 giờ của Messenger đóng (R15) | Quyết định của chủ dự án: "đầu ra là chạy thật, những phần đã nêu là điều kiện cần" |
| 2026-10-12 | **Giọng văn trả lời khách** (§5.8): `STYLE.md` theo sandbox, ví dụ giọng thật của doanh nghiệp, skill v3 có bảng chiến thuật theo `reason_code`, bộ eval 25 tình huống | Chủ dự án yêu cầu tin nhắn không giống AI; tham khảo agency-agents (MIT) |
| 2026-10-13 | **Trả lời lượt khách khi chưa có người trả lời** (WP16, §5.7 loại `turn`): tin của khách được gom thành *lượt* (chờ khách nhắn xong, mặc định 30 giây), rồi LLM đọc cả lượt và quyết định `reply` / `wait` / `handoff` / `none`. Auto → gửi ngay trong cửa sổ tự do, kèm dòng xưng AI; manual → nháp trả lời hiện ngay ở đầu trang duyệt. Không bắn khi nhân viên đang trực hội thoại đó. A2, N7, §1.1, §1.4, §11 sửa theo. **Ghi lại để trung thực:** N7 cũ cấm đúng việc này vì đối thủ cho miễn phí; ranh giới mới là AI *lấp chỗ chưa có người*, không thay nhân viên, và điểm bán vẫn là không để rơi + trí nhớ + theo sát | Quyết định của chủ dự án: "đó là vấn đề cơ bản trong chăm sóc khách hàng" — khách nhắn mà không ai trả lời là kiểu rơi khách đầu tiên |
| 2026-10-12 | **Cửa sổ kênh đã đóng → nháp tuyến `offchannel`** (`draft.route`): nhân viên gọi điện/nhắn Zalo theo gợi ý, không bao giờ vào outbox (kể cả `auto`, kể cả nút duyệt). Validator kiểm cả **ngày** (dd/mm) như số liệu | R39: lời hẹn xa trên Messenger tới ngày thì cửa sổ đã đóng, hệ thống im → rơi khách; R38: ngày khai giảng sai lọt tới khách |
| 2026-10-14 | **Mục tiêu đầu tiên: AI tự tư vấn khoá học và hỗ trợ khách, giảm tối đa việc nhân viên phải can thiệp.** Handoff chỉ còn cho: ưu đãi/giảm giá ngoài catalog, khiếu nại, thứ catalog không ghi, đòi gặp người. Đăng ký, học thử, hoàn phí, ưu đãi trong catalog, cách học, lộ trình do AI tự trả lời; nhân viên chỉ còn việc thao tác thật (gửi phiếu, xếp giờ). **Bỏ khoản đặt cọc giữ chỗ** khỏi dữ liệu mẫu. Catalog mẫu được làm giàu (phương pháp, lộ trình, đối tượng từng khoá). Chất lượng đo bằng hội thoại kịch bản mơ hồ chạy LLM thật rồi đọc tay, không dùng thang chấm tự động. Skill `tra-loi-khach` v8. **Chưa làm:** tool AI tự gửi phiếu/chốt lịch (cần thiết kế riêng, chạm ngân sách L3) | Quyết định của chủ dự án 2026-10-14. Chưa có bằng chứng từ khách thật |
| 2026-10-17 | **Bỏ L3: không còn đóng băng code tới G2.** Xây toàn bộ roadmap T1/T2 (§7.1, §7.3) song song với việc đi tìm khách, vì chưa đưa được khách thật vào để chạy G1.5. Cổng G1/G1.5/G2 và mốc giết (L4, L6), L8, các bất biến A1–A9, nhóm C trước khi chạm dữ liệu thật **vẫn giữ nguyên**. **Ghi lại để trung thực:** đây là lần thứ hai chủ dự án chọn xây trước khi có khách, trái khuyến nghị của hội đồng và của LESSONS (hướng cũ chết vì đúng kiểu này). Rủi ro chịu có chủ đích: phần xây thêm không có bằng chứng từ khách, và có thể thành `workflow_service` bản mới | Quyết định của chủ dự án 2026-10-17: "hiện tại không thể đưa khách thật vào, hãy xây hệ thống hoàn chỉnh trước và trong thời gian xây dựng vừa đi tìm khách" |
| 2026-10-17 | **Xây xong đợt 2–6 của §7.3 trên dữ liệu giả lập** (497 test, cortex-leads ≈ 7.990 dòng gồm bridge — vượt ngân sách v0 5.000 vì L3 đã bỏ): WP17 thông báo đẩy Telegram (R58), WP18 AI giữ chỗ học thử + validator kiểm giờ/URL, WP19 cron mẫu + sandbox `owner_digest`, WP20 `http_readonly`, WP21 AI tổng (tín hiệu 0 token → đề xuất, người duyệt; LLM chỉ viết tóm tắt tuần từ số), WP22 form skill + giai đoạn shadow thật, WP23 MCP ngoài chỉ đọc có ghim định nghĩa, WP24 `add_tag`/`add_note` qua outbox, WP25 thẻ chiến lược, WP26 multi-cell (router). **Chưa kiểm trên thế giới thật:** Page Pancake/Messenger, LLM thật cho các đoạn mới, MCP server thật, bridge nào hỗ trợ nhãn/ghi chú (REVIEW R70–R84). Đây là *khả năng*, không phải bằng chứng: G1 vẫn chưa có cuộc nói chuyện nào | Quyết định của chủ dự án 2026-10-17 (dòng trên). Chưa có bằng chứng từ khách |
| 2026-10-21 | **G0: chốt ngành khoá học / du học** (mặc định của §2.3, vì chưa có ngành nào đạt quy tắc ≥ 15 chủ quen). **Hướng mở rộng đã chọn, chưa phải phạm vi:** sau tư vấn, hỗ trợ học viên (lịch, học bù, học phí, kết quả); chờ khách xác nhận theo G2.5. **Yêu cầu của chủ dự án:** hoàn thiện đầy đủ tính năng trước rồi mới giao trung tâm dùng. **Ghi trung thực:** yêu cầu này mâu thuẫn với mốc G1 (23/10) và L4 (trượt G1 thì dừng code mới); chưa sửa mốc, chủ dự án cần quyết rõ | Quyết định của chủ dự án 2026-10-21. Chưa có bằng chứng từ khách |
| 2026-10-21 | **Giao diện chính (console) cho chủ và nhân viên** thay cho trang `/staff` thử nghiệm: quản lý kỹ năng, tạo sandbox, trò chuyện với AI tổng, hộp thư, dừng khẩn cấp. Thiết kế ở `pencil/` (5 màn). **Tech stack chốt:** React 19 + TypeScript + Vite (SPA), Tailwind CSS v4, TanStack Query, React Router, lucide-react, Vitest. Backend thêm API JSON `/api/v1` trong FastAPI hiện có, cùng cookie phiên và CSRF với `/staff`; bản build tĩnh do chính FastAPI phục vụ ở `/app` (một dịch vụ, một origin). **Ràng buộc giữ nguyên:** trò chuyện với AI tổng chỉ thấy số liệu và metadata (§5.6), không bao giờ nội dung tin nhắn | Quyết định của chủ dự án 2026-10-21 ("hãy xây dựng fe theo thiết kế, chọn tech stack phù hợp"). Chưa có bằng chứng từ khách |
| 2026-10-21 | **Quy ước dữ liệu và thời gian** (§5.13): một nơi ghi ngày giờ (`core/timefmt.py`, `format.ts`), UTC `Z` qua API, hiển thị theo múi giờ doanh nghiệp, giờ học thử chỉ có một nguồn (`valid_until`), ngân sách theo ngày của doanh nghiệp (đổi hành vi: reset lúc 00:00 giờ Việt Nam thay vì 07:00). Có test chặn kiểu định dạng mới | Quyết định của chủ dự án 2026-10-21. Phát hiện từ rà soát: giờ học thử có hai nguồn không kiểm khớp (AI báo khách theo chữ, hệ thống giữ chỗ theo giờ thật) |
| 2026-10-21 | **Danh sách sáng nay phủ cả việc còn nợ; khách bảo dừng thì dừng ngay; báo cáo tháng.** (1) `morning_list` thêm ba nhóm tính từ trạng thái: lời hẹn đã tới hạn, khách im sau khi nhân viên trả lời, việc bị trần nháp bỏ qua (sweeper chỉ bắn một lần mỗi đợt im nên trước đây các ca này mất). (2) Trước đây không đường nào đặt `contact.opted_out`; nay luật 0 token tại ingest đặt ngay khi khách nói dừng, chỉ người gỡ được (khác các gợi ý khác: không chờ xác nhận, vì nhầm thì nhân viên gỡ, sót thì gửi tin khách đã cấm). (3) Báo cáo tháng (ngày 1, 8:00). Sửa nhận định trước đó: runner đã có chốt chặn `PENDING_OUTCOME`, nên hẹn không cần thêm chốt ở engine | R107, R109, R111 (REVIEW). Chưa có bằng chứng khách thật; thuộc H1 (lead rơi) và nhóm C |
| 2026-10-22 | **Sandbox `lesson_recap` (WP31): bản ghi buổi học → bài học, bài tập về nhà → kênh Mezon của đội.** Thuộc hướng mở rộng "hỗ trợ học viên" (2026-10-21), đưa tới G2.5 bằng cách cho trung tâm thấy việc giáo viên đỡ mất giờ soạn tổng kết. Nguồn: thư mục Drive (hoặc thư mục máy) → ffmpeg → Whisper (API hoặc chạy tại chỗ) → LLM, tên/SĐT/email che trước LLM. Đầu ra chỉ đi **nội bộ** (`notify`, đích `mezon`), không qua `outbox`, nên A9 không bị chạm; giáo viên tự chuyển tiếp cho phụ huynh. Bản đầu chỉ tổng kết chung lớp + bài tập; nhận xét riêng từng học sinh để sau vì Whisper không biết ai đang nói. **Chưa có bằng chứng từ khách** (`docs/customers/` còn trống) và làm sát mốc G1 (23/10): ghi trung thực theo L4/L8. Âm thanh có thể là giọng trẻ em: chỉ chạy bản ghi thật khi có đồng ý của phụ huynh và đã chọn Whisper chạy tại chỗ hoặc có DPA (§6) | Quyết định của chủ dự án 2026-10-22. Chưa có bằng chứng từ khách |
| 2026-10-22 | **Dựng sandbox mới bằng khối dùng lại (WP32), không làm trình dựng cho chủ.** Bốn chuyên gia (kiến trúc, an toàn/pháp lý, sản phẩm, luồng việc) cùng kết luận: gỡ phần chung khỏi `lesson_recap` thành khối viết bằng mã; chủ trung tâm chỉ chọn mẫu và chỉnh tham số; **chưa** làm trình ghép chặng (giống `workflow_service` đã chết, và §11 cấm chuỗi bước trong manifest). Manifest YAML tuần tự chỉ xét khi có sandbox thứ ba. Đợt này làm bốn việc thấp rủi ro: (1) registry `SandboxKind` thay sáu bảng cứng theo `purpose`; (2) khối LLM `ask_json` + `read_in_pieces` (hỏi lại khi sai schema, đoạn hỏng thì chia đôi, lưu ghi chú từng đoạn); (3) chốt nhận việc `claimed_at` (worker quay lại sau TTL không ghi đè worker mới); (4) chặn SSRF cho webhook (allowlist host, https, IP công cộng). **Hoãn có chủ đích:** `work_item` chung, trần quyền `effect_ceiling` + `lint_sandbox`, `Sink` registry, mã hoá địa chỉ webhook và buộc đích gửi theo sandbox (cần trước classroom_grader), `classroom_grader` (cần OAuth giáo viên, validator điểm A7, nhóm C). **Ghi trung thực:** vẫn chưa có bằng chứng từ khách (L1) và `lesson_recap` đã xây trước khi có khách xin, trái §11 "sandbox thứ hai trước G2.5" | Quyết định của chủ dự án 2026-10-22, theo khuyến nghị của bốn chuyên gia. Chưa có bằng chứng từ khách |
| 2026-10-22 | **Sandbox `classroom_grader` (WP33): chấm bài và giao bài trên Google Classroom, người duyệt mọi thứ.** Chủ dự án yêu cầu làm tiếp sau WP32. **Ràng buộc đã xác minh từ tài liệu Google:** chỉ dự án Cloud (OAuth client) **đã tạo** bài tập mới ghi được điểm cho bài đó (`PERMISSION_DENIED` nếu khác), nên bài giáo viên tạo tay trên giao diện chỉ được **gợi ý điểm**, không ghi lại. **Thiết kế:** AI chỉ *đề xuất* (điểm theo tiêu chí kèm trích dẫn nguyên văn từ bài, lời nhận xét); validator kiểu A7 chặn điểm ngoài thang, tổng không khớp, trích dẫn không có trong bài; **chỉ giáo viên bấm duyệt mới ghi điểm lên Classroom** (đường ghi duy nhất, không qua LLM) và chỉ với bài do chính ứng dụng tạo; AI soạn đề thì giáo viên duyệt rồi mới tạo bài. Thông báo đẩy chỉ có số lượng, không tên học sinh hay điểm. Dùng chung khối hàng việc (`work/queue.py`, rút từ `lessons/job.py`) thay vì chép lần hai. **Chưa làm:** gửi điểm riêng từng học sinh qua kênh ngoài Classroom (Zalo cá nhân không có API; đích gửi theo sandbox R120 chưa xong), chấm tệp PDF/ảnh, nhận xét theo từng học sinh dài hạn. **Ghi trung thực:** vẫn chưa có bằng chứng từ khách (L1); điểm và bài của trẻ em thuộc nhóm C (đồng ý của phụ huynh, DPA, thời hạn lưu): **chỉ chạy dữ liệu giả hoặc lớp thử của chính chủ dự án** cho tới khi nhóm C xong | Quyết định của chủ dự án 2026-10-22. Chưa có bằng chứng từ khách |
| 2026-10-23 | **`classroom_grader` đọc thêm PDF, Word, âm thanh và video (WP34).** Chủ dự án hỏi bài nộp ở các định dạng đó có xử lý được không. PDF có lớp chữ (PDF scan bị từ chối `NO_TEXT_LAYER`, không đọc chữ viết tay); Word (.docx); âm thanh và video **chỉ lấy tiếng** (ffmpeg bỏ hình), tối đa 15 phút, chép lời bằng đúng khối Whisper của `lesson_recap`. Ảnh, slide, bảng tính vẫn bị từ chối, không chấm một phần bài. Tên tệp không bao giờ đưa cho LLM (thường chứa tên học sinh). Khi chữ có thể sai theo cách học sinh không gây ra (bản chép lời, PDF mất bảng), đề xuất điểm kèm lưu ý để giáo viên nghe hoặc xem lại trước khi duyệt. Vẫn chưa có bằng chứng từ khách (L1); dữ liệu và giọng nói của học sinh thuộc nhóm C | Quyết định của chủ dự án 2026-10-23. Chưa có bằng chứng từ khách |
| 2026-10-23 | **Trang Buổi học nhận bản ghi tải lên trực tiếp (WP35), đường thứ hai ngoài thư mục Drive.** Chủ dự án yêu cầu: tải lên ngay trong trang, danh sách có xem lại và nội dung bên cạnh. Tệp lưu trên đĩa máy chủ dưới tên do máy chủ đặt (`UPLOAD_DIR/<tenant>/<id>.<đuôi>`), gửi lên bằng PUT với thân là chính tệp (ghi thẳng xuống đĩa, từ chối từ kích thước khai báo, `ffprobe` kiểm có âm thanh); người tải chọn ngôn ngữ (vi/en/tự nhận ra) vì ép nhầm ngôn ngữ làm bản chữ vô nghĩa (đã gặp ở bài nói chấm bài). Phát lại qua endpoint có phiên đăng nhập, hỗ trợ tua (Range), `no-store`. Có thể **xoá riêng tệp gốc, giữ lại chữ** vì giọng nói của lớp là phần cá nhân nhất. Bàn về gộp ba trang (Hộp thư, Buổi học, Chấm bài/Bài tập) thành một màn "Việc cần làm" **để sau** (khuyến nghị: menu tự sinh theo loại sandbox trước, hàm chiếu chung và bộ vẽ trang khai báo khi có ≥5 loại việc). Vẫn chưa có bằng chứng từ khách (L1); giọng nói của học sinh thuộc nhóm C | Quyết định của chủ dự án 2026-10-23. Chưa có bằng chứng từ khách |
| 2026-10-23 | **Bản ghi tải lên lưu ở Drive của chính giáo viên, Cortex chỉ giữ chữ (WP36).** Chủ dự án hỏi bản tải lên có lưu về Drive tương ứng của họ không; chọn phương án "chỉ lưu ở Drive của giáo viên". Mỗi giáo viên một `drive_target` (đăng nhập OAuth của họ, mã hoá) với quyền `drive.file`: Cortex chỉ chạm được thư mục và tệp **chính nó tạo** ("Cortex – bản ghi buổi học"), không đọc phần còn lại của Drive. Tệp tải lên lưu tạm trên máy chủ, vòng xử lý nền tải lên Drive (theo đoạn, thử lại được), chuyển thành chữ, rồi **xoá bản tạm** khi việc xong (hoặc hết số lần thử) **với điều kiện** bản ở Drive đã có; chưa lên được Drive thì giữ tệp vì đó là bản duy nhất. Lý do Drive thay vì máy chủ: giọng nói của lớp (có thể trẻ em) ở lại tài khoản của chính trung tâm, Cortex giữ ít dữ liệu cá nhân hơn (nhóm C). Đổi lại không phát lại ngay trong trang (có nút mở trong Drive). Service account không dùng được vì không có dung lượng Drive | Quyết định của chủ dự án 2026-10-23. Chưa có bằng chứng từ khách |
| 2026-10-23 | **Một đường xử lý duy nhất, và trình duyệt tải thẳng lên Drive (WP37).** Chủ dự án muốn tải lên chỉ là đưa tệp vào Drive (không hai đầu xử lý) và bản ghi không đi qua máy chủ Cortex. Quyết định: `POST /lessons/upload/session` kiểm yêu cầu (đuôi, cỡ khai báo, ngôn ngữ, sandbox, kỹ năng, Drive, hạn mức), nhờ Drive của giáo viên mở một phiên upload resumable (thư mục theo dõi, tên, thuộc tính `cortex_language` do **server** chốt) và trả URL phiên; trình duyệt gửi từng đoạn 8 MB thẳng lên Google. Cortex không thấy một byte nào, không còn tệp tạm. **Bảo mật:** token OAuth không rời server; URL phiên chỉ cho ghi một tệp mới ở đúng chỗ đã chốt, hết hạn sau khoảng một tuần, không ghi vào nhật ký; `Origin` gửi Google lấy từ `CL_PUBLIC_BASE_URL` (khi chạy thật; yêu cầu có `Origin` lạ bị từ chối), bỏ trống khi chạy local thì dùng địa chỉ request đang đến; CSP `connect-src` mở thêm đúng `www.googleapis.com`; hạn mức `CL_UPLOAD_PER_USER_DAY`=20 và `CL_UPLOAD_PER_TENANT_DAY`=100 tính từ nhật ký (`lesson.upload_started`), vì server không còn chặn được bằng ffprobe. Đổi lại phải **kiểm lại ở vòng theo dõi**: sau khi tải tệp về, `probe` loại tệp không phải âm thanh/video (`NOT_MEDIA`) hoặc không có tiếng (`NO_AUDIO`) trước khi tốn Whisper. Vòng theo dõi (`discover`) là nơi duy nhất tạo bài học, đọc ngôn ngữ từ thuộc tính (chỉ vi/en/auto). Gỡ hẳn: `PUT /lessons/upload`, kho tải lên trên máy chủ (`CL_UPLOAD_DIR`), `send_to_drive`, `UploadStore`, xoá tệp gốc. Xem lại: `GET /lessons/{id}/media` truyền qua từ Drive bằng service account, không lưu. Chưa kiểm trên Google thật: `drive.file` ghi vào thư mục có sẵn; service account thấy tệp giáo viên tải vào; Google áp dung lượng khai báo; CORS với `Origin` đã gửi; `Range` đọc được qua CORS | Yêu cầu chủ dự án 2026-10-23 |
| 2026-10-30 | **Gói "Lớp học" (WP38): `class` làm gốc, `assignment` là thực thể thật, chính sách tự động theo lớp.** Chủ dự án muốn gộp Bài giảng, Chấm bài, Bài tập thành một cấu trúc Lớp học → Bài giảng/Bài tập → Bài nộp, và cho phép đặt theo từng lớp: tổng kết bài giảng tự gửi hay chờ duyệt; chấm bài thủ công / AI đề xuất người duyệt / tự ghi điểm. Quyết định: thiết kế lại DB (xem [`PHIEU-lop-hoc.md`](PHIEU-lop-hoc.md)): bảng `class` thay `lesson_source` + `classroom_source`, trỏ tới cả hai sandbox; `assignment` thay `assignment_draft` + `grading_guide`; `grade_item` đổi thành `submission`. Mặc định `review`/`review`: giữ nguyên "người duyệt mọi thứ" (2026-10-22), chế độ tự ghi điểm phải bật tường minh, chỉ chủ, có audit, chỉ cho bài do Cortex tạo và AI đã kiểm chứng đủ. Nhận xét cho học sinh **không** tới Classroom (API chỉ ghi điểm và trả bài): giữ nội bộ, giao diện ghi "tự động ghi điểm". `classroom_publish` bỏ, quy về chế độ tổng kết. **Ghi trung thực:** `docs/customers/` trống nên không có bằng chứng từ khách (L1); mốc G1 (23/10) đã qua, kết quả chưa ghi vào đây; tự ghi điểm đụng dữ liệu trẻ em (nhóm C), chỉ chạy trên dữ liệu giả | Yêu cầu chủ dự án 2026-10-30. Chưa có bằng chứng từ khách |
| 2026-11-04 | **Bài tập mẫu (WP44) và chọn tệp đính kèm từ Google Drive (WP45).** (1) Mỗi doanh nghiệp đặt tên các **loại lớp**; mỗi loại có các **bài tập mẫu** mang đúng các ô của form soạn bài (tên mẫu bắt buộc, còn lại tuỳ chọn; không giữ hạn nộp, giờ đăng, học sinh vì thuộc một lần đăng). Lớp **không** gắn với loại nào: form soạn bài hỏi loại lớp rồi bài tập; chọn xong chỉ điền ô, mọi kiểm tra vẫn chạy ở đường tạo bài như cũ. Bảng `class_kind`, `assignment_template` (RLS), quyền `grading.use`. (2) **Ngoại lệ có giới hạn của "token OAuth không rời server" (WP37):** hộp chọn tệp của Google (Picker) chạy trong trình duyệt và cần access token ở đó. `POST /google/picker/token` cấp một access token **mới, thu hẹp còn `drive.file`** (refresh có tham số `scope`), sống khoảng một giờ, không bao giờ vào log hay nhật ký (nhật ký chỉ ghi "mở hộp chọn tệp của tài khoản X"); **refresh token không rời server**. Tệp giáo viên chọn trong Picker được cấp cho ứng dụng theo `drive.file`, không mở thêm gì khác trong Drive của họ. Drive mở ra là của **tài khoản Google đã nối** (lớp: tài khoản thao tác trong khoá Classroom, vì nó là bên tạo bài), không phải tài khoản của trình duyệt. Cần `CL_GOOGLE_PICKER_API_KEY` và `CL_GOOGLE_PROJECT_NUMBER`; thiếu thì nút tắt và chưa đính kèm được tệp (giao diện đã bỏ "Tải tệp từ máy" và "Dán địa chỉ" theo yêu cầu 2026-11-04; đã gỡ endpoint `PUT /classes/{id}/assignment-files` và cột `class.files_folder_id`, migration 0043); CSP của trang chỉ mở thêm domain Google khi đã cấu hình. **Chưa kiểm trên Google thật:** Picker mở được với token thu hẹp; tệp chọn qua Picker đính kèm được vào bài do tài khoản Classroom tạo; CSP đủ cho Picker | Yêu cầu chủ dự án 2026-11-04. Chưa có bằng chứng từ khách |
| 2026-11-06 | **Vai trò giáo viên, phạm vi theo lớp (WP46).** Chủ dự án dùng một tài khoản Google chung cho mọi lớp và muốn mỗi giáo viên quản lý được mọi thứ trong lớp mình phụ trách. Quyết định: thêm vai trò `teacher` và bảng `class_teacher` (RLS), chủ giao lớp ở trang Nhân viên & quyền. Phạm vi là một quyền, không phải một phép so sánh vai trò: `classes.all` chỉ nằm ở `owner`, nên vai trò khác mặc định **không** thấy lớp nào. Endpoint trỏ tới một lớp, bài tập, bài nộp hay buổi học khai `need_class("quyền")`; endpoint liệt kê tự lọc; lớp ngoài phạm vi trả 404 giống hệt thứ không tồn tại và ghi `permission.refused`. Một test buộc mọi endpoint dùng quyền của lớp phải khai đã xử lý phạm vi thế nào. **Giáo viên làm được trong lớp mình:** buổi học (xem, tải lên, xoá, duyệt tổng kết), bài tập (soạn, AI soạn, sửa, đăng, xoá), chấm bài, đổi tên lớp, `recap_mode`, `grading_mode` giữa `manual` và `review`. **Vẫn chỉ chủ:** tạo, xoá, tắt, nối lại lớp; đổi tài khoản Google, khoá học, webhook; bật `auto_write` (giữ quyết định 2026-10-30). Giáo viên không có Hộp thư, kỹ năng, sandbox, dữ liệu; bài tập mẫu chỉ xem vì là của cả doanh nghiệp (`templates.manage`). **Cập nhật cùng ngày:** `staff` giờ chỉ chăm sóc khách hàng (hộp thư, nháp, đặt lịch, xem kỹ năng và giá) và **không còn quyền nào của lớp học** (lớp, buổi học, chấm bài, bài tập mẫu); việc lớp học là của chủ và giáo viên. **Rủi ro còn lại của tài khoản chung:** hộp chọn tệp cần access token trong trình duyệt. Với giáo viên, server chỉ cấp token của đúng tài khoản lớp họ phụ trách và hộp chọn chỉ mở tab tải lên, không duyệt Drive; nhưng token `drive.file` vẫn chạm được mọi tệp Cortex đã tạo hoặc đã được chọn trên tài khoản đó trong khoảng một giờ, nên đây là ranh giới cho người dùng thường, không phải cho người cố ý (REVIEW R165). Bài đăng trên Classroom mang tên tài khoản chung; ai đăng thật chỉ có trong nhật ký Cortex. Chưa bằng chứng từ khách (L1); mốc G1 đã qua và kết quả vẫn chưa ghi; dữ liệu lớp thật vẫn chờ nhóm C | Yêu cầu chủ dự án 2026-11-06. Chưa có bằng chứng từ khách |

> **Chưa có bằng chứng nào từ người thật.** Phần sản phẩm (§1–4) là giả thuyết cho tới khi §3 có số. Phần nền tảng (§5) được xây theo §7.2, và **chỉ đúng phạm vi v0**. Mọi thứ ngoài v0 vẫn mở theo cổng.

Bản 1 lưu ở [`archive/DESIGN-v1-2026-08.md`](archive/DESIGN-v1-2026-08.md). Các chú thích `DESIGN x.y` trong code cũ (`backend/`, `mezon_bot/`…) trỏ về bản đó.

**Mục lục:** 0 Luật · 1 Sản phẩm · 2 Người dùng và tiền · 3 Giả thuyết · 4 Nguyên tắc sản phẩm · 5 Kiến trúc · 6 Pháp lý và kênh · 7 Kế hoạch và lộ trình xây · 8 Cam kết · 9 Rà soát · 10 Nợ phải trả · 11 Không làm

---

## 0. Luật dùng tài liệu — chống lệch hướng

Cortex đã đổi hướng bốn lần, lần nào cũng theo cùng một kiểu: tài liệu viết luật hay, tay làm việc khác, tài liệu không được sửa.

**L1 — Trước mọi việc, trả lời ba câu. Không trả lời được câu nào thì không làm.**

1. Việc này thuộc cổng nào, hoặc thuộc gói việc nào trong phạm vi v0 (§7.2)?
2. Việc này đưa mình tới gần cổng đó bằng cách nào?
3. Bằng chứng nào trong `docs/customers/` cho thấy khách cần nó? Với gói việc v0, câu trả lời được chấp nhận là "nằm trong phạm vi v0 đã ghi ở §7.2".

**L2 — Đổi hướng thì sửa tài liệu trước, code sau.** Thêm một dòng vào bảng sửa đổi, kèm bằng chứng hoặc lý do. Các câu kiểu "tôi nghĩ là", "chuyên gia nói", "mô phỏng cho thấy" không được tính là bằng chứng *từ khách*.

**L3 (BỎ 2026-10-17) — ~~Ngoài phạm vi v0, code sản phẩm đóng băng tới cổng G2.~~** Không còn đóng băng. Ngân sách 5.000 dòng chỉ còn là mốc đo phạm vi v0, không chặn code mới. Thay vào đó, mỗi gói việc mới vẫn phải qua L1 (thuộc cổng nào, đưa tới cổng bằng cách nào) và L7 (phiếu / manifest trước code). Mốc giết L4/L6 vẫn có hiệu lực: trượt G1 thì **dừng mọi code mới**, không gia hạn.

**L4 — Mốc giết là mốc giết.** Trượt mốc thì làm đúng điều cột "không đạt" ghi, không gia hạn.

**L5 — Có một người ngoài giữ mốc** (§8). Người này xem §9 mỗi tuần và có quyền tuyên bố dừng.

**L6 — Không có hướng thứ sáu trên codebase này.** Trượt G4 thì Cortex thành portfolio.

**L7 — Mỗi năng lực, skill, connector đều cần một phiếu hoặc manifest (§5.4, §5.8) trước khi viết code.**

**L8 (mới) — Giờ code ≤ giờ nói chuyện với khách, tính từ 2026-10-17.** Vượt tỷ lệ này một tuần thì ghi dòng đỏ ở §9. Vượt hai tuần liên tiếp thì dừng code cho tới khi cân lại.

---

## 1. Sản phẩm là gì

### 1.1 Câu định nghĩa

> **Mỗi sáng, nhân viên tư vấn nhận danh sách khách đã hỏi mà đang bị bỏ rơi — kèm lý do đoán vì sao họ im và một tin nhắn nháp. Nhân viên bấm gửi. Không khách tiềm năng nào rơi mà không ai biết.**
>
> **Khách nhắn mà chưa ai trả lời thì không phải chờ:** khi khách nhắn xong, AI đọc cả lượt và trả lời (auto) hoặc đặt sẵn nháp trả lời cho nhân viên (manual) — chỉ khi chưa có người trả lời.

Đây là **sandbox đầu tiên** (`customer_care`) trên nền tảng ở §5. Các sandbox khác chỉ mở theo cổng G2.5.

### 1.2 Vấn đề — *giả thuyết, chưa kiểm*

Doanh nghiệp bán dịch vụ cần tư vấn trả tiền quảng cáo để có khách nhắn tin. Một phần đáng kể khách đã hỏi giá **không được ai liên hệ lại đúng lúc**. Chủ cũng **không nhìn thấy** lead nào đang rơi, và rơi trong tay ai.

Điều chưa biết, và nó quyết định tất cả: khách im vì *không ai nhắn lại* (cứu được), hay vì đang dò giá, chê giá (không cứu được)? H1 ở §3 kiểm đúng điều này.

### 1.3 Vì sao chỗ này còn trống

"AI trả lời khách" đã thành hàng miễn phí: Botcake AI Agent, Meta Business AI tiếng Việt (beta từ 4/2026), Sapo. CRM ngành thì nắm khâu sau khi khách đã thành khách hàng. Còn khâu **từ lúc lead hỏi tới lúc có lịch hẹn** vẫn nằm trong Pancake, Excel và đầu của telesale. Khe hở này hẹp: Pancake có thể lấp nó trong 12–18 tháng.

**Chỗ khác biệt của Cortex là trigger theo thời gian cộng hiểu ngữ cảnh**: hỏi lại đúng hẹn, đúng khách, với một thông tin mới, và qua tay nhân viên.

### 1.4 Cortex KHÔNG phải

Chatbot *thay* nhân viên (AI chỉ trả lời khi chưa có người, §5.7 `turn`) · CRM · inbox đa kênh · trợ lý cá nhân · nền tảng automation chung · công cụ BI · công cụ xếp hạng nhân viên.

---

## 2. Người dùng, người trả tiền, ngành

### 2.1 Ba vai — không được trộn

| Vai | Ai | Cần gì |
|---|---|---|
| **Người dùng hằng ngày** | Nhân viên tư vấn / telesale | Biết hôm nay chăm ai trước, có sẵn câu để gửi, công chốt vẫn là của mình |
| **Người trả tiền** | Chủ / quản lý | Nhìn thấy lead đang rơi ở đâu; tiền quảng cáo không bị đốt |
| **Khách cuối** | Người hỏi giá | Được trả lời đúng, không bị đeo bám, biết khi nào mình đang nói với AI |

Danh sách lead rơi là **danh sách việc cho nhân viên**, không phải bảng xếp hạng lỗi. Báo cáo về từng người gửi tới chính người đó trước.

### 2.2 Giá thử và kênh bán

- **Giá:** setup 3 triệu + 3–4 triệu/tháng/cơ sở. Mốc so sánh là lương một telesale (15–25 triệu).
- **Lưu ý từ mô phỏng:** chủ spa và shop online neo giá theo phần mềm, khoảng 0,3–2 triệu. Mức 3–4 triệu chỉ hợp với ngành khoá học hoặc nha khoa.
- **Kênh bán thử đầu tiên:** agency chạy quảng cáo tin nhắn, chia 20–30%.

### 2.3 Ngành — ✅ **ĐÃ CHỐT 2026-10-21: khoá học / du học** (theo mặc định; chưa có danh sách ≥ 15 chủ doanh nghiệp)

**Quy tắc:** chọn ngành mà người xây quen được **≥ 15 chủ doanh nghiệp**. Nếu không có ngành nào như vậy, mặc định là **khoá học / du học**.

| Ngành | Hạng trung bình | Mạnh | Yếu |
|---|---|---|---|
| **Khoá học / du học** | ~2,6 · *vững nhất* | Quản lý đau rõ; CRM ngành ít AI; chu kỳ chốt dài | Hứa visa / học bổng; phụ huynh dùng Zalo cá nhân |
| Nội thất | ~2,8 | An toàn pháp lý | Khách nằm trong Zalo cá nhân; báo giá tuỳ đo đạc |
| Nha khoa | ~3,2 · *nhiều tiền nhất* | Đang trả 10–15 triệu cho người trực page | Dữ liệu sức khoẻ; tư vấn dễ bị coi là khám chữa bệnh |
| Linh kiện, spa, xe | ≥ 3,8 | — | **Không chọn** |

---

## 3. Giả thuyết và phép thử — ghi ngưỡng trước, không sửa sau khi chạy

**Cách chạy.** Làm tay với 3–5 doanh nghiệp:

1. Mỗi sáng, lọc khách đã hỏi giá mà im ≥ 24 giờ, hoặc đã tới ngày khách tự hẹn.
2. Đoán lý do khách im, soạn nháp.
3. Gửi nháp cho nhân viên của doanh nghiệp. **Nhân viên bấm gửi.**
4. Chia nhóm thử / nhóm đối chứng theo ID chẵn / lẻ.

Từ khi v0 chạy được, bước 1–2 do v0 làm và người xây duyệt.

| # | Giả thuyết | Đo | **Bác bỏ nếu** |
|---|---|---|---|
| H0 | Tiếp cận được ngành | Số cuộc nói chuyện, số doanh nghiệp cho xem inbox | Tới 23/10: < 15 cuộc **hoặc** < 3 doanh nghiệp |
| H1 | Lead rơi là có thật và đủ lớn | % lead hỏi giá mà không ai liên hệ, không có lịch trong 24 giờ | Bất kỳ điều nào: < 10% ở cả 3 doanh nghiệp · < 10 lead rơi/tháng/doanh nghiệp · > 30% "im lặng" thực ra đã chuyển sang Zalo cá nhân hoặc điện thoại |
| H2 | Nhân viên dùng nháp | % nháp được gửi nguyên văn hoặc sửa nhẹ | < 40% sau tuần đầu |
| H3 | Theo sát cứu được khách | Tỷ lệ khách trả lời và đặt lịch trong 7 ngày, so với nhóm đối chứng | Hơn < 10 điểm %, **hoặc** bị chặn / phàn nàn > 5% |
| H4 | Có người trả tiền | Chuyển khoản thật | Tới 31/12: < 3 khách trả ≥ 2 triệu/tháng |

**Chỉ số vận hành, ghi từ ngày đầu:**

- số hội thoại mới mỗi ngày;
- số tin mỗi ngày;
- giờ cao điểm và độ dồn của nó;
- tỷ lệ lead rơi;
- số nháp nhân viên duyệt được trong một buổi sáng;
- thời gian khách trả lời;
- số lead đã hết cửa sổ nhắn trước khi có ai chạm tới;
- số phút làm tay mỗi sáng.

---

## 4. Nguyên tắc sản phẩm

Vi phạm một nguyên tắc là đủ lý do từ chối một thiết kế.

**N1 — AI đứng sau người là *mặc định*, không phải giới hạn năng lực.** Mặc định, người nói chuyện với khách là nhân viên dùng tên thật, còn AI soạn nháp. AI **có năng lực tự gửi** (A9), nhưng chỉ dùng được khi **skill** và **bridge** cùng cho phép. Khi AI tự gửi, nó phải:

- xưng là trợ lý AI (Luật AI 134/2025);
- chỉ nói dữ kiện có trong catalog (N2);
- dừng và chuyển sang người khi gặp `must_handoff`.

**N2 — Mọi con số khách nhìn thấy phải trỏ về một dòng catalog.** Không có dữ liệu thì dùng câu mẫu cố định. Không để LLM lấp chỗ trống.

**N3 — Luật kênh là ràng buộc cứng.** Lõi tính cửa sổ nhắn theo khách × kênh (`window_state`) và gửi kèm trong mỗi lệnh chiều ra. **Bridge** là tầng giao tiếp với nền tảng, nên là nơi quyết định cuối: có gửi được trên nền tảng đó, lúc đó hay không. Ví dụ, tag HUMAN_AGENT của Messenger chỉ dành cho người gõ tay, nên bridge từ chối lệnh do `ai:*` gửi trong khung này.

**N4 — Duyệt nháp là mặc định.** Tự gửi là ngoại lệ, phải bật tường minh theo từng skill (`send_policy.mode: auto`). Khuyến nghị chỉ bật khi skill đó đã có thống kê duyệt tốt (§5.8, "thang bật tự gửi").

**N5 — Tối đa 3 lần chạm, mỗi lần phải có thứ mới.** Không có thông tin mới → `blocked: NO_NEW_INFO`. Khách có tín hiệu tiêu cực thì dừng ngay.

**N6 — Không làm nhân viên phiền hơn tự làm.** Duyệt dưới 10 giây một nháp. Mỗi nhân viên có trần nháp/ngày. **Sức duyệt của nhân viên chính là ngân sách của hệ thống.**

**N7 — Không xây lại thứ đối thủ cho miễn phí:** inbox, CRM, chatbot kịch bản. Trả lời lượt khách (§5.7 `turn`) có trong lõi nhưng chỉ để **lấp chỗ chưa có người**; nó dùng chung validator, trí nhớ và catalog với phần theo sát, và không phải điểm bán (sửa 2026-10-13).

**N8 — Ghi lại mọi quyết định, kể cả quyết định im lặng.**

---

## 5. Kiến trúc

> **Tầng:** **T0** = script / MCP cục bộ phục vụ việc làm tay · **v0** = nền tảng tối thiểu đang xây (§7.2) · **T1** = sau G2 · **T2** = sau G3/G4.

### 5.0 Bất biến kiến trúc — đúng từ dòng code đầu tiên

| # | Bất biến | Vì sao |
|---|---|---|
| A1 | `tenant_id` có trên mọi bảng, mọi hàng đợi, mọi log. Postgres RLS theo `app.tenant_id` | Cách ly; mở đường cho mô hình cell / silo |
| A2 | **Không gọi LLM theo mỗi tin nhắn.** Tin khách được gom theo **lượt** (chờ khách nhắn xong); luật 0 token chạy trước (nhân viên đang trực, opt-out, ngân sách); LLM gọi tối đa một lần mỗi lượt, và chỉ khi có việc thật | Tải và chi phí tỷ lệ theo *việc*, không theo *lưu lượng* |
| A3 | Tenant, actor, scope **do server điền** (từ connector key hoặc `RunContext`), không bao giờ lấy từ body hay tham số LLM | Chống giả danh và rò dữ liệu |
| A4 | Mọi lời gọi ra ngoài (kênh, LLM) đi qua **một cổng**, có rate limit theo tenant | Không để tenant ồn ào lấn tenant khác; kiểm soát quota |
| A5 | Mỗi lượt chạy agent **không giữ trạng thái**. Trạng thái nằm trong DB | Muốn mở rộng thì thêm worker |
| A6 | Engine **chỉ đọc profile / manifest**, không biết tên profile nào | Thêm agent = thêm cấu hình, không thêm nhánh code |
| A7 | Validator 0 token chạy **bên trong** tool ghi | LLM không thể bỏ qua |
| A8 | Ingest trả 202 ngay; idempotent theo `(tenant, connector, external_id)` | Không mất tin, không xử lý trùng |
| A9 | **Chỉ có một đường để gửi tin cho khách:** tool `send_message` → `outbox` → bridge chiều ra (§5.2). Không runner hay tool nào được gọi API của kênh trực tiếp. Lệnh gửi chỉ đi khi **cả hai lớp chặn cho phép**: skill (`send_policy`, mặc định `draft`) và bridge (`outbound`, luật nền tảng). Lõi chỉ giữ một **sàn** không tắt được: kill switch, khách opt-out, audit, idempotency, dòng xưng AI | Gửi được hay không là chuyện cấu hình; *gửi qua đâu* là cấu trúc. Một đường duy nhất thì chặn, đo và tắt được ở một chỗ |

### 5.1 Bốn lớp

```
 ┌── LỚP 1: GIÁC QUAN ─────────────────────────────────────────────────────┐
 │ Bridge bên ngoài (Pancake forwarder, n8n, bot…) ─► POST /ingest/v1/events│
 │ ĐỒNG HỒ: sweeper next_check_at · cron slot                               │
 └────────────────────────────────┬────────────────────────────────────────┘
 ┌── LỚP 2: TRÍ NHỚ (Postgres + RLS) ──▼────────────────────────────────────┐
 │ tenant · sandbox · connector · contact · conversation · message ·        │
 │ catalog_item · followup_job · trigger_run · draft · decision_log · ...   │
 └────────────────────────────────┬────────────────────────────────────────┘
        sự kiện miền: customer.message · staff.reply · conversation.silent · conversation.promised_date_reached · ...
 ┌── LỚP 4: NÃO ───────────────────▼────────────────────────────────────────┐
 │ engine trigger (0 token) → chọn ĐÚNG 1 skill → RunContext + Context Builder│
 │ → một lượt LLM, ≤ 3 vòng tool, ≤ 8 tool → kết quả có cấu trúc            │
 └────────────────────────────────┬────────────────────────────────────────┘
 ┌── LỚP 3: TAY CHÂN ──────────────▼────────────────────────────────────────┐
 │ Tool (vỏ) → Command (validate · authorize · audit · idempotency) → DB/cổng│
 └─────────────────────────────────────────────────────────────────────────┘
```

Skill nằm ở lớp 4, năng lực ở lớp 3, thời gian thực ở lớp 1. Ba thứ này không được trộn vào nhau.

### 5.2 Lớp 1 — Giác quan: cổng nhận chuẩn + bridge + đồng hồ

**Thêm kênh không phải sửa code lõi.** Phần code riêng của từng kênh (cách xác thực, chữ ký webhook của kênh, polling, phân trang, phân biệt người gửi) nằm ở **bridge bên ngoài lõi**. Lõi chỉ có **một** cổng nhận, theo một định dạng chuẩn.

```
Kênh (Pancake, Zalo OA, Messenger, Mezon, form…) → BRIDGE (bot / n8n / script)
    → dịch sang Cortex Event Format, ký HMAC → POST /ingest/v1/events → lõi
```

**Cortex Event Format v1** (hợp đồng chính thức, có version):

```json
POST /ingest/v1/events
Headers: X-Connector-Id: <id>
         X-Timestamp: <unix seconds>                  // chống phát lại: lệch > 300s → 401
         X-Signature: sha256=<hex HMAC_SHA256(secret, timestamp + "." + body)>
{
  "format": "cortex.event/1",
  "events": [{
    "type": "message.created",                 // message.created | conversation.updated | contact.updated
    "external_id": "pancake:page123:msg_998",  // BẮT BUỘC, khoá chống trùng
    "occurred_at": "2026-10-10T14:03:22+07:00",
    "channel": {"kind": "messenger", "account_ref": "page123"},   // kind ∈ danh mục kênh của lõi
    "conversation": {"external_id": "conv_55"},
    "contact": {"external_id": "psid_8812", "display_name": "...", "phone": "..."},
    "sender": {"role": "customer"},            // customer | staff | bot — BẮT BUỘC
    "staff": {"external_id": null},
    "text": "...", "attachments": [],
    "meta": {}                                 // tuỳ ý, không được dùng để ra quyết định
  }]
}
→ 202 {"results": [{"external_id": "...", "status": "accepted|duplicate|rejected", "error": null}]}
```

**Lõi phải tự làm, không tin lời bridge:**

- Tenant suy ra từ connector, không bao giờ lấy từ body.
- Schema được validate chặt. Lỗi thì `rejected` kèm lý do, không đoán.
- `external_id` là unique.
- **Luật cửa sổ kênh** do lõi tự tính theo `channel.kind`, từ bảng chính sách kênh trong lõi.
- Rate limit, kích thước batch và kill switch được áp theo từng connector.

**Mức tin cậy của connector:**

| Mức | Ai viết | Được làm |
|---|---|---|
| `official` | Người xây | Đầy đủ |
| `partner` | Agency | Như `official`, sau khi qua contract test |
| `custom` | Khách tự viết | Chỉ được nạp dữ liệu; không kích hoạt hành động nhạy cảm cho tới khi qua contract test |

`sender.role` là trường sống còn: `conversation.silent` đúng hay sai phụ thuộc vào nó. Vì vậy **mỗi bridge phải có contract test chạy trên dữ liệu mẫu**.

**Chiều ra: Cortex Action Format v1** (thiết kế; xây khi mở theo §7). Lõi gọi vào bridge bằng webhook có ký HMAC (cùng secret của connector). Bridge là **tầng giao tiếp giữa hệ thống và nền tảng**, và là một trong hai lớp chặn.

```json
POST <connector.outbound.url>                       // Cortex → bridge
Headers: X-Cortex-Timestamp, X-Cortex-Signature: sha256=<HMAC(secret, ts + "." + body)>
{
  "format": "cortex.action/1",
  "action_id": "<uuid>",                     // idempotency — bridge phải bỏ qua action_id đã xử lý
  "type": "send_message",                    // send_message | add_tag | add_note (T2)
  "channel": {"kind": "messenger", "account_ref": "page123"},
  "conversation": {"external_id": "conv_55"},
  "actor": "ai:customer_drafter@1",          // hoặc "staff:<ref>"
  "text": "...", "disclosure": "Trợ lý AI của <doanh nghiệp>",   // disclosure bắt buộc khi actor là ai:*
  "window": {"open": true, "basis": "free", "expires_at": "..."}, // lõi tính, bridge dùng để kiểm
  "source": {"skill": "hoi-lai-khach-im@1", "run_id": "<uuid>"}
}
→ 200 {"status": "sent", "external_message_id": "..."}
  | {"status": "refused", "reason": "OUTBOUND_DISABLED|AI_SEND_DISABLED|WINDOW_CLOSED|PLATFORM_POLICY|QUIET_HOURS|RATE_LIMIT|NOT_SUPPORTED"}
  | {"status": "error", "retryable": true|false}
```

- **Bridge chặn** những gì thuộc về nền tảng: chiều ra tắt; tài khoản này không cho AI gửi; ngoài cửa sổ; `ai:*` trong khung HUMAN_AGENT; giờ yên lặng của doanh nghiệp; quota của nền tảng; kênh không hỗ trợ.
- **Lõi coi `refused` là kết quả bình thường** (`blocked` + lý do, ghi `decision_log`), không retry. Chỉ `error` có `retryable=true` mới được thử lại, có backoff.
- **Chỉ connector `official` hoặc `partner` được bật chiều ra.** `custom` thì không, vì lõi không kiểm được bridge đó có thi hành luật nền tảng hay không.
- **Tin đã gửi quay về qua chiều vào** như mọi tin khác (`sender.role = bot` nếu là AI, `staff` nếu nhân viên bấm), nên đồng hồ và lịch sử luôn khớp với thực tế trên nền tảng.

Nếu bridge chạy trên dịch vụ bên thứ ba (n8n cloud, Zapier), dữ liệu đi qua họ, nên họ phải được ghi vào DPA như **bên xử lý phụ**.

**Đồng hồ — lõi của "trigger theo thời gian".** "Khách im" là sự vắng mặt của một sự kiện, nên không webhook nào báo được. Mỗi hội thoại có `next_check_at` (có index), được tính lại khi có tin mới. Sweeper lấy việc tới hạn:

```sql
SELECT id FROM conversation WHERE next_check_at <= now()
 ORDER BY next_check_at LIMIT 100 FOR UPDATE SKIP LOCKED;
```

Chi phí tỷ lệ theo *số việc tới hạn*, không theo *tổng dữ liệu*.

**Sự kiện miền:** `customer.message` · `staff.reply` · `conversation.silent` · `conversation.promised_date_reached` · `draft.expired` · `cron.tick`.

### 5.3 Lớp 2 — Trí nhớ

**Bảng (v0):**

- `tenant` · `sandbox` · `connector(secret_hash, trust, status)`
- `contact` · `conversation(next_check_at, last_customer_at, last_staff_at, owner_staff_ref, promised_date, offchannel_contact)` · `message`
- `catalog_item(version, valid_until)` · `ingest_event(raw, status)`
- `followup_job(dedupe_key UNIQUE)` · `trigger_run` (**không có cột văn bản**)
- `draft(status, text, claims, reason_code)` · `staff_action` · `decision_log` · `action_log`

Tất cả có `tenant_id` đứng đầu index và có RLS.

**Bộ nhớ chia theo phạm vi** (không có kho chung tìm bằng embedding — LESSONS 3):

| Loại | Phạm vi | Ai ghi | Ai đọc |
|---|---|---|---|
| Hồ sơ khách: nhu cầu, ngày khách tự hẹn, người quyết định, đã liên hệ ngoài kênh | Một khách | Customer run (kèm `msg_id` làm bằng chứng) hoặc nhân viên | Customer run của chính khách đó; người |
| Catalog, FAQ | Một tenant | Người | Mọi run trong tenant, chỉ đọc |
| Cách làm việc của chủ | Một tenant | Cấu hình skill có version, có duyệt | Customer run, qua skill |

Dữ liệu thô bị xoá theo hạn ghi trong DPA.

### 5.4 Lớp 3 — Tay chân (năng lực)

**Ba tầng code. LLM chỉ chạm tầng ngoài cùng:**

```
Tool (vỏ: ≤ 2 câu mô tả + schema) → Command (validate · authorize · thực thi · audit · idempotency) → DB / cổng
```

**Phiếu năng lực (L7):**

```yaml
name: draft_followup
effect: read | internal | customer       # server dùng để quyết propose hay commit
tier: v0 | T1 | T2
gate: G1.5
evidence_required: [msg_ids]
args: {...}  returns: {status, data, note?, violations[], next_step}
blocked_codes: [...]  guards: [tenant, kill_switch, rate_limit]  audit: action_log  revert: ...
```

**Hợp đồng chung:**

```yaml
server_context: tenant_id · actor (ai:<profile>@<ver> | staff:<id>) · run_id · idempotency_key   # không bao giờ lấy từ LLM
mode: read → chạy · internal → AI được commit, hoàn tác được · customer → chỉ tool `send_message`; ai:* được commit khi skill `send_policy.mode=auto`, ngược lại thành propose (nháp). Commit = ghi outbox, bridge mới là nơi gửi thật
status: ok | proposed | blocked | not_found | ambiguous | error
note: BẮT BUỘC khi kết quả rỗng ("Không có… — đừng suy đoán")      # code cũ: kết quả rỗng thì agent bịa 6/6 lần
blocked ≠ error: WINDOW_CLOSED · NO_CONSENT · TOUCH_LIMIT · UNVERIFIED_CLAIM · FORBIDDEN_PHRASE · OWNER_IS_HUMAN · OPTED_OUT · NO_NEW_INFO
refs: khớp 1 → dùng · khớp nhiều → ambiguous kèm danh sách · không khớp → not_found kèm danh sách   # không fuzzy, không gọi LLM
next_step: một câu, không chứa quy trình
cùng một tool trả INVALID_ARGS 2 lần → handoff
```

**Danh mục năng lực:**

| Miền | v0 | T1 | T2 |
|---|---|---|---|
| Hội thoại | `read_messages` (đã che PII) | `handoff` | — |
| Khách | `read_contact` | `add_contact_note`, `set_promised_date`, `log_offchannel_contact` | `merge_contacts` |
| Phát hiện | `list_dropped_leads` (luật 0 token) | — | — |
| Catalog | `lookup_catalog` | `get_faq` | `propose_catalog_edit` |
| Nháp | `draft_followup` (+ `validate_draft` bên trong) | nháp tự huỷ khi khách nhắn thêm | `auto_reply_offhours` |
| Gửi | — | `send_message` (effect `customer`; `validate_draft` + sàn A9 bên trong; ghi `outbox`) · worker chiều ra | — |
| Nhân viên | `record_staff_action` (sự kiện từ UI, không phải tool LLM) | `create_staff_task` | — |
| An toàn | `redact_pii`, `decision_log`, kill switch theo tenant / skill / connector | `check_consent`, `export/delete_contact` | — |

**Không bao giờ giao cho AI:**

- gửi tin cho khách **ngoài** tool `send_message` (A9);
- báo giá hoặc giảm giá ngoài catalog;
- cam kết kết quả;
- nhắn qua Zalo cá nhân;
- đổi người phụ trách;
- xoá hoặc chặn khách;
- xác nhận thanh toán;
- chẩn đoán từ ảnh;
- xếp hạng nhân viên;
- gọi điện.

### 5.5 Lớp 4 — Não: profile, RunContext, ba loại run

**Một engine, nhiều profile.** Mỗi lượt chạy là một phòng kín logic. Không có agent sống lâu: mỗi sự kiện dựng một run mới, chạy xong thì bỏ.

| | **Customer run** | **Headless run** | **Supervisor ("AI tổng", T2)** |
|---|---|---|---|
| Đầu vào | Tin của khách — **không tin được** | Dữ liệu trong DB | Read-model metadata |
| Phạm vi | **Đúng một hội thoại** + hồ sơ khách đó + catalog | Theo job | Toàn tenant, **không có văn bản** |
| Trần effect | `internal`; `customer` khi skill có `send_policy.mode: auto` | `internal` | Chỉ được đề xuất |
| Đầu ra | Có cấu trúc: `{act, reason_code, claims[], text}` | Có cấu trúc | Đề xuất tạm dừng hoặc hạ version |

**Profile:**

```yaml
id: customer_drafter  version: 1  audience: customer  input_trust: untrusted
context_sources: [conversation:{scope}, contact_profile:{scope}, catalog:tenant, skill:{id}@{ver}]
tool_allowlist: [read_messages, read_contact, lookup_catalog, draft_followup]
effect_ceiling: internal  memory_scope: contact  output_schema: DraftResult
model: lite  max_tool_calls: 3  timeout_s: 30  token_budget: 8000
```

```python
@dataclass(frozen=True)
class RunContext:            # server dựng cho mỗi run, LLM không sửa được
    run_id: UUID; tenant_id: UUID; sandbox_id: UUID
    profile: str; profile_version: int
    principal: Principal     # Customer(contact_id) | Staff(id) | System(job)
    scope: Scope             # {conversation_id} | {tenant} | {job_id}
    trigger_event_id: str | None
```

**Bốn chốt chặn (trong code, không trong prompt):**

1. Context Builder chỉ nạp các `context_sources` đã khai.
2. RLS: mỗi run thực hiện `SET LOCAL app.tenant_id`.
3. Tool lấy scope từ `RunContext`, và chặn mọi tool có effect vượt trần.
4. Mỗi hội thoại chỉ có một run tại một thời điểm (advisory lock).

**Mẫu Dual-LLM.** Văn bản tự do của khách **không bao giờ** chảy vào ngữ cảnh của agent có quyền rộng hơn.

### 5.6 Sandbox và AI tổng

**Sandbox** là một không gian AI làm một loại việc, cách ly với các sandbox khác.

```yaml
sandbox:
  id, tenant_id, name
  purpose: customer_care | owner_digest | ...     # v0 chỉ có customer_care
  profile: customer_drafter@1
  skills: [skill_id@ver]                           # hướng dẫn, có version, có duyệt
  connectors: [connector_id]                       # kênh / nguồn được gắn
  tools: allowlist ⊆ profile.tool_allowlist
  data_scope: các hội thoại / nguồn được chạm
  egress_schema: thứ DUY NHẤT được đi ra (metadata, reason_code, nháp vào hàng duyệt)
  isolation: logical | process | dedicated         # v0: logical
  budget: {runs_per_day, drafts_per_staff_per_day, tokens_per_day}
  status: active | paused                          # kill switch
```

**Khi nào bắt buộc tách sandbox.** Đây là luật 0 token. AI tổng chỉ đề xuất, người xác nhận. Cấu hình thuộc **bất kỳ** trường hợp nào dưới đây thì phải chạy trong sandbox:

- chạm dữ liệu khách;
- có đầu vào không tin được;
- gắn kênh có khách ở đầu kia;
- dùng MCP bên ngoài.

**Chiều đi của thông tin:**

| Chiều | Được đi | Cấm |
|---|---|---|
| Sandbox → AI tổng | Metadata của `trigger_run` (trạng thái, `reason_code` dạng enum, mã bị chặn, token, `act`, kết quả từ nhân viên) + kết quả theo `egress_schema` | Văn bản tin nhắn, prompt, văn bản tự do của khách |
| AI tổng → sandbox | Cấu hình có version, qua duyệt | Ra lệnh khi đang chạy; đọc vào bên trong |
| Sandbox ↔ sandbox | Không đi thẳng; chỉ cùng đọc dữ liệu tenant (catalog) | Mọi đường khác |
| Người → nội dung thô | Giao diện có audit | AI tổng đọc hộ |

**Read-model của AI tổng** là `trigger_run` / `decision_log` **không có cột văn bản**. Có role DB riêng với `GRANT` theo cột. Số tổng hợp chỉ hiện khi n ≥ 5.

### 5.7 Engine trigger

Phát triển từ bản 1 §16, phần chưa từng được code.

| Loại | Ví dụ | Đầu ra cho phép | Tầng |
|---|---|---|---|
| **relative** | Im 24 giờ sau khi hỏi giá; tới ngày khách hẹn; nháp hết hạn | `draft_for_staff` | v0 |
| **turn** (lượt khách) | `conversation.awaiting_reply`: khách nhắn xong (im ≥ `after`, mặc định 30 giây) mà chưa ai trả lời | `send_to_customer` (auto) hoặc nháp trả lời ngay (manual); LLM chọn `reply` / `wait` / `handoff` / `none` | v0 (WP16) |
| **event** | `customer.message`, `staff.reply` | Huỷ hoặc dời trigger khác (reset `next_check_at`, huỷ nháp). Im lặng | v0 |
| **cron** | 7h45 gom danh sách; tóm tắt tuần cho chủ | `staff_task` / `owner_digest`, bản đầu dùng **template** | T1 (template) / G2.5 (LLM) |
| **condition** | Lead rơi tuần này tăng X% | `owner_digest`, predicate có tên, 0 token | G2.5 |

**Quy tắc engine:**

- **Đầu ra:** `draft_for_staff | send_to_customer | staff_task | owner_digest | none`. `send_to_customer` chỉ hợp lệ khi skill khai `send_policy.mode: auto`. Kể cả khi đó, lệnh vẫn đi qua `send_message` → outbox → bridge, và bridge có quyền từ chối (A9). Khi bị từ chối, kết quả chuyển thành `draft_for_staff` nếu skill khai `fallback: draft`.
- **Lượt khách (`turn`, WP16):** mỗi tin khách dời mốc `reply_check_at = tin cuối + after` (cửa sổ trượt); tin của nhân viên hoặc bot xoá mốc. Tới mốc mà vẫn chưa ai trả lời thì bắn `conversation.awaiting_reply`, trừ khi nhân viên vừa nhắn trong hội thoại đó ≤ 10 phút (đang trực — AI không chen ngang). LLM đọc cả lượt:
  - `reply` → nháp; auto thì đi `send_message` ngay (không chờ giờ làm việc: khách vừa nhắn), manual thì nháp lên đầu trang duyệt với nhãn "khách đang chờ";
  - `wait` → khách có vẻ chưa nói xong ("cho em hỏi…"): dời mốc thêm 2 phút, tối đa 1 lần, sau đó phải chọn khác;
  - `handoff` → câu cần người (giảm giá, khiếu nại, ngoài catalog, muốn đăng ký): thẻ "Cần người trả lời" cho nhân viên, **không bao giờ tự gửi**, và thẻ không hết hạn khi khách nhắn tiếp (chỉ hết khi nhân viên trả lời). Ở `auto`, khách vẫn được báo ngay một câu "đã chuyển bạn tư vấn" (model viết, qua validator; hỏng thì dùng câu cố định `handoff_reply` của skill) — **khách không bao giờ nhắn mà không ai đáp** (2026-10-14);
  - câu `reply` bị validator chặn → model được viết lại **một lần** kèm lý do; vẫn hỏng → thành `handoff`. Model không được khẳng định điều catalog không ghi, không hứa việc nó không tự làm (giữ chỗ, kiểm tra, xếp lớp) — cụm hứa nằm trong `never_say`;
  - `none` → không cần trả lời ("ok", "cảm ơn", sticker).
  Tin trả lời lượt **không tính** vào trần 3 lần chạm của phần theo sát (N5); nhân viên tự trả lời thì nháp lượt đó hết hạn.
- **Khớp 0 token, chỉ so bằng.** Predicate là một *tên* trong registry viết bằng code, không phải biểu thức. Thấy mình muốn thêm `$or` hoặc chuỗi bước là dừng.
- **Idempotency:** `UNIQUE(trigger_id, dedupe_key)`. `dedupe_key` có một trong các dạng:
  - `event_id`;
  - `cron:<id>:<slot>`;
  - `silent:<conv>:<last_customer_msg_id>` (mỗi đợt im chỉ bắn một lần).
- **Chống vòng lặp:** event có `source=engine` không bao giờ khớp lại. `causation_depth ≤ 1`.
- **Chọn trước, viết sau:** xếp hạng ứng viên bằng 0 token, lấy top K theo trần nháp/ngày, rồi mới gọi LLM.
- **Chống bão tải:** mục tiêu là *sẵn sàng trước giờ*, không phải chạy đúng giờ. `not_before = slot − 2h + hash(tenant) % 105 phút`. Hướng ưu tiên hơn: **viết nháp khi nhân viên mở danh sách**, nhờ đó không có bão tải và không có nháp cũ.
- **Mặc định là không làm gì:** `{"act":"none"}`. Tỷ lệ im phải ≥ 50%.
- **Ngân sách cứng trong code:** trần run / tenant / ngày. Lỗi 3 lần liên tiếp thì trigger chuyển `disabled` và báo một lần.
- **"Hằng tuần hỏi han khách tiềm năng"** = một danh sách cho nhân viên, chia theo trạng thái cửa sổ:
  - còn cửa sổ → nháp; hoặc tự gửi nếu skill `auto` và bridge cho phép;
  - trong 7 ngày HUMAN_AGENT → nháp, người gửi (phải xác minh, xem §10);
  - đã opt-in marketing → bắt buộc có `new_info_ref`, chủ duyệt;
  - không còn đường nào → nhắc nhân viên gọi, hoặc bỏ. Cửa sổ kênh đã đóng → nháp tuyến `offchannel` cho nhân viên gọi/Zalo, không bao giờ vào outbox.

  Không có thông tin mới → `NO_NEW_INFO`.
- **Thẻ chiến lược (T2):** tối đa 3 thẻ, mặc định 0 thẻ. Mỗi thẻ là **một thay đổi cấu hình skill**, kèm quan sát, n, phép thử và nút Duyệt. Duyệt thì sinh skill chạy shadow. Không bao giờ là văn xuôi.

### 5.8 Manifest và vòng đời plugin

**Quy ước chung để thêm Skill / tool / kênh mà không sửa code lõi.** Người viết manifest trên thực tế là người xây, rồi tới agency. Chủ doanh nghiệp chỉ thấy *form* sinh từ manifest.

**Skill** (`sandboxes/<sandbox>/skills/<name>/SKILL.md`, frontmatter theo chuẩn Agent Skills + trường riêng):

```yaml
---
name: hoi-lai-khach-im
description: "Nháp hỏi lại khách hỏi giá rồi im ≥24h. KHÔNG dùng khi khách đã chê giá/đã mua."
version: 1
status: draft | shadow | live
trigger: {kind: relative, on: conversation.silent, match: {intent: hoi_gia}, after: 20h}   # 20h: trước khi cửa sổ 24h của Messenger đóng (R15)
requires_tools: [read_messages, read_contact, lookup_catalog, draft_followup]   # ⊆ profile, ≤ 8
output_kind: draft_for_staff
limits: {max_touches: 3, min_gap: 24h, fire_limit: 1, expires_after: 14d}
must_handoff: [giảm giá, khiếu nại, ngoài catalog, khách đòi gặp người]
never_say: [cam kết kết quả, "tốt nhất", "rẻ nhất"]
approval: always
send_policy:                       # lớp chặn 1 — theo skill. Bỏ trống = theo chế độ của sandbox
  mode: auto | manual              # ghi đè `sandbox.send_mode` (mặc định doanh nghiệp mới: manual)
  auto_when: {window: free, max_per_contact_per_day: 1}   # chỉ được siết thêm, không nới sàn
  fallback: manual                 # bị chặn (luật kênh, validator, must_handoff, bridge từ chối) → chuyển nhân viên duyệt
eval: {cases: eval/, min_pass: 0.9}
---
(thân: cách làm + 3 cặp vào/ra mẫu)
```

**Giọng văn.** `STYLE.md` theo sandbox + ví dụ giọng thật của doanh nghiệp trong `data/voice/<tenant_id>/<sandbox>.md` (không commit; ưu tiên hơn ví dụ trong skill) được nạp vào ngữ cảnh, cắt theo `token_budget`; cụm "giọng AI" đưa vào `never_say` để validator chặn. Bộ eval `sandboxes/<sandbox>/eval/cases.yaml` chạy bằng `dev/eval_skills.py`.

**Hai chế độ gửi.** `auto`: AI soạn → validator → gửi ngay qua bridge (trong giờ làm việc; ngoài giờ xếp hàng chờ). `manual`: AI soạn → validator → **thông báo nhân viên duyệt**; nhân viên bấm Duyệt thì **hệ thống gửi qua bridge** (không phải chép sang Pancake). Chế độ đặt ở **sandbox** (mặc định cho cả doanh nghiệp) và **ghi đè được theo skill**. Ở `auto`, mọi tin không được phép gửi tự động (ngoài cửa sổ tự do, HUMAN_AGENT, validator chặn, `must_handoff`, bridge từ chối) **tự rơi về `manual`**.

**Thang bật auto (khuyến nghị, không phải luật của lõi):** chỉ đổi một skill sang `send_policy.mode: auto` khi skill đó đã có ≥ 20 nháp được gửi nguyên văn liên tiếp, tỷ lệ phải sửa < 5%, và 0 lần bị chặn vì `UNVERIFIED_CLAIM`. Sau khi bật, nếu có phàn nàn, khách chặn, hoặc nhân viên báo sai, thì hạ skill về `manual` và báo chủ.

**Tool connector** (T1: `http_readonly`; T2: `mcp`):

```yaml
id: catalog_sheet  kind: builtin | http_readonly | mcp
source: {...}  pin_sha256: <hash của tools/list + schema>
expose: [{remote: get_rows, as: lookup_catalog, description: "<do người duyệt viết>"}]
effect: read            # người duyệt gán; server tự khai khác → chặn
egress_allow: [...]  args_redacted: true  result: untrusted  secret: vault://...
```

**Channel connector** (cho cổng nhận chuẩn ở §5.2):

```yaml
id: conn_xxx  tenant: ...  trust: official | partner | custom
channel_kind: messenger | zalo_oa | ...     # ∈ danh mục kênh của lõi; luật cửa sổ do lõi tính, bridge thi hành
emits: [message.created, conversation.updated]
outbound:                                    # lớp chặn 2 — tầng giao tiếp với nền tảng. Bỏ trống = tắt
  enabled: false
  url: https://...                           # bridge nhận Cortex Action Format v1
  capabilities: [send_message]               # add_tag, add_note (T2)
  policy: {ai_send: false, quiet_hours: "21:00-08:00", max_per_minute: 20}
contract_test: passed_at                     # bật outbound cần contract test cho cả chiều ra
```

**Lint khi nạp:**

- `requires_tools` ⊆ allowlist, tối đa 8;
- `effect` không vượt trần;
- `on` thuộc từ vựng sự kiện;
- `match` chỉ so bằng, không có `$or`;
- frontmatter tối đa ~15 trường;
- `send_policy.mode: auto` thì bắt buộc `requires_tools` có `send_message` và `output_kind: send_to_customer`;
- hash khớp.

**Vòng đời:**

- **draft:** lint + eval offline.
- **shadow:** chạy trên sự kiện thật, ghi `decision_log`, không vào hàng duyệt. Tối thiểu 7 ngày hoặc 30 run, đọc tay 20.
- **live:** có người ký.

Version là bất biến. Rollback = trỏ con trỏ `live` về version cũ. Kill switch ở mức tenant / skill / connector. Tự tắt khi lỗi 3 lần, khi hash lệch, hoặc khi `blocked` vọt.

**"Agent biết làm gì":**

1. **Router 0 token:** trigger chọn đúng một skill, nên mỗi run chỉ có khoảng 3 tool.
2. Mô tả tool do mình viết lại.
3. Ví dụ vào/ra nằm trong thân skill.
4. Eval là cổng bắt buộc.

**MCP bên ngoài (T2):**

- không bao giờ được vào customer run;
- chỉ `effect: read`;
- chỉ remote HTTP, có egress allowlist;
- không chạy stdio của bên thứ ba;
- lượt có kết quả MCP ngoài thì tắt mọi tool ghi.

### 5.9 MCP — vị trí

MCP (spec 2026-07-28) là giao thức **kéo**: model gọi tool. Thông báo chỉ tới client, **không đánh thức model**. Vì vậy MCP **không phải event bus**.

| Câu hỏi | Quyết định |
|---|---|
| Giác quan / đánh thức AI | Tự xây (§5.2, §5.7) |
| Nguồn sự thật của tool | Registry riêng (§5.4) |
| Runner gọi tool | Gọi trực tiếp trong process |
| MCP dùng ở đâu | **v0:** MCP server cục bộ `cortex-leads` (stdio, chỉ đọc), cho người xây làm việc tay cùng Claude Desktop / Code |
| MCP Pancake của bên thứ ba | Không. Token Pancake có toàn quyền page |
| Tính năng tasks / subscriptions của MCP | Không dùng |
| Bảo mật | `redact_pii` chạy **bên trong** server trước khi trả kết quả |

### 5.10 Hiệu năng và mở rộng

CPU và DB không phải nút thắt cho tới vài trăm doanh nghiệp, **với điều kiện giữ A2**.

Nút thắt thật, theo thứ tự sẽ gặp:

1. **API kênh.** Pancake cho 5 req/s mỗi page, nên cần token bucket mỗi page, nằm ở bridge.
2. **Quota LLM.** Một cổng duy nhất, có ưu tiên, có prompt caching. **Không dùng 9Router `free_auto` cho khách thật.**
3. **Tenant ồn ào.** Lập lịch xoay vòng theo tenant.
4. **Quét theo thời gian.** Dùng `next_check_at` + `SKIP LOCKED`.
5. **Sức duyệt của nhân viên.** Trần nháp/ngày.

**Mô hình tenant:** pool (mặc định) → cell (từ ~300–500 doanh nghiệp) → silo (khách lớn trả tiền cho việc đó). Chuyển được mà không viết lại, nhờ A1 + A4 + bảng định tuyến `tenant → cell`.

**Lộ trình hạ tầng:**

| Quy mô | Hạ tầng | Chi phí / tháng |
|---|---|---|
| T0–v0 | Laptop + Docker Postgres | ~0 + LLM |
| ≤ 20 doanh nghiệp | 1 VM 2 vCPU / 4 GB, backup S3 | ~$30–50 + LLM |
| ~100 doanh nghiệp | 2 node ingest + LB, 2–4 worker, Postgres managed, partition `message` | ~$300–600 |
| 1.000+ doanh nghiệp | Cell | Tỷ lệ theo số cell |

### 5.11 Code — thư mục mới, mang theo rất ít

**Sản phẩm mới nằm ở `cortex-leads/` ở gốc repo** (theo quyết định của chủ dự án). Không import gì từ `backend/`; code cũ chỉ được **chép rồi sửa**, có chú thích nguồn.

> ⚠️ Repo này đang **công khai**. `cortex-leads/` không bao giờ chứa dữ liệu khách, secret, catalog hay prompt riêng của khách (`data/` được gitignore toàn bộ). **Trước khi nhận dữ liệu của khách đầu tiên:** chuyển `cortex-leads/` sang một repo private, hoặc chuyển cả repo này sang private.

```
cortex-leads/
  pyproject.toml · docker-compose.yml (Postgres test :5544) · Makefile · README.md
  cortex_leads/
    config.py            secret bắt buộc, không có mặc định, từ chối giá trị đã lộ
    core/                RunContext, Principal, Scope, ids, errors, envelope ToolResult
    db/                  models, session (SET LOCAL app.tenant_id), RLS · migrations/ (alembic)
    ingest/              Cortex Event Format v1 (pydantic), HMAC, API /ingest/v1/events, chuẩn hoá
    clock/               sweeper next_check_at, tính next_check_at
    triggers/            engine: registry predicate, dedupe, followup_job, trigger_run
    skills/              loader SKILL.md, lint, registry version / status; profiles/ (YAML)
    sandbox/             model sandbox, budget, kill switch, quy tắc tách
    tools/               registry, phiếu năng lực, refs, empty note, các tool v0
    privacy/             redact_pii
    guard/               validator (catalog, từ cấm, số lần chạm, opted-out, cửa sổ)
    channels/            bảng chính sách kênh (dữ liệu)
    llm/                 cổng LLM (port model_client), rate limit theo tenant, FakeProvider cho test
    runner/              Context Builder, customer run, kết quả có cấu trúc
    review/              API hàng nháp cho nhân viên, staff_action
    supervisor/          read-model metadata (không có văn bản)
    mcp_server/          MCP stdio chỉ đọc
  bridges/pancake/       bridge official: poll Pancake (chỉ GET) → Event Format → POST
  sandboxes/customer_care/   profile + skills/*/SKILL.md mẫu
  tests/                 unit + integration (Postgres thật)
  data/                  gitignore
```

**Mang sang từ code cũ (port, không import):**

| Mang sang | Nguồn |
|---|---|
| Retry và phân loại lỗi LLM (không có fallback) | `backend/app/ai/agents/model_client.py` |
| Giờ làm việc / khung trống | `backend/app/services/availability.py` (`_gaps`, `is_in_quiet_hours`) |
| Kết quả rỗng phải kèm note | `backend/app/ai/tools/empty_result.py` |
| Giải tham chiếu không đoán → `refs.py` | `backend/app/ai/tools/project_ref.py` |
| Cứu trường điền nhầm chỗ | `backend/app/ai/tools/title_fallback.py` |
| Pipeline validate → quyền → chạy → audit | `backend/app/commands/registry.py`, `schemas.py` |
| Làm sạch args trước khi log | `backend/app/ai/agents/tool_registry.py` (`_sanitize_args`) |
| Idempotency theo `external_id` | `backend/app/services/task_ingest.py` |
| Dòng cuối prompt vẽ shape | `backend/app/services/memory_extraction_prompt.py` (`response_shape`) |
| Ý engine trigger | `docs/archive/DESIGN-v1-2026-08.md` §16 |

**Không mang:** `agent_service.py`, 22 tool cũ, `Procedure`, Attention Gate, `mezon_bot`, `workflow_service`, OCR / STT, frontend.

**Hệ cũ** (`backend/`, `mezon_bot/`, `frontend/`, …) **đã gỡ khỏi repo ngày 2026-10-10**, chỉ còn trong lịch sử git (commit `0a22e33`); xem [`LEGACY.md`](LEGACY.md). Server cũ: vá bảo mật (§10), dump DB, tắt — **không merge nhánh gỡ vào `develop` trước khi tắt server**.

### 5.12 Bộ chạy thử (0 đồng, chạy trên laptop)

| Thành phần | Chọn | Vai trò |
|---|---|---|
| Kênh hội thoại | **Facebook Page thử + Meta app chế độ phát triển** | Hội thoại thật với tester (người có vai trò trong app); không cần App Review |
| Đường hầm HTTPS | Cloudflare Tunnel (hoặc ngrok) | Webhook của Meta / Twenty về laptop |
| Kết quả bán hàng | **Twenty CRM** (Docker, nguyên bản, không fork) | Deal "Won" → `deal.updated` |
| Bảng giá, đơn ghi tay | **Google Sheet** | Catalog và đơn hàng theo cách SME đang làm |
| LLM | `FakeProvider` khi test; lớp lite (Claude Haiku 5.5) khi chạy thử | Đo chất lượng nháp thật |
| Nhân viên | Trang duyệt (WP13) + MCP trên Claude Desktop | Duyệt nháp, ghi trí nhớ |

**Kịch bản chuẩn:** tester nhắn hỏi giá → người xây trả lời trong hộp thư Page (nhận diện là nhân viên) → tester im (skill thử `after: 5m`) → AI soạn nháp có nguồn → duyệt trên trang duyệt → tin gửi qua bridge → tester "tuần sau chị bàn với chồng" → ghi ngày hẹn + người quyết → kéo deal "Won" trong Twenty → hẹn đóng → số liệu AI tổng không có chữ của khách. Chạy lại ở chế độ `auto`.

**Giới hạn:** chỉ tester có vai trò trong app mới nhắn được; khách thật cần Pancake hoặc Advanced Access (§6). Payload Twenty / Messenger khác Pancake / KiotViet — bridge cho phần mềm của khách vẫn phải làm và test trên payload thật của họ.

### 5.13 Quy ước dữ liệu và thời gian (2026-10-21)

Một nơi duy nhất viết ngày giờ ra: `cortex_leads/core/timefmt.py` (backend) và `web/src/components/format.ts` (giao diện). Test chặn mọi chỗ khác tự gọi `isoformat`, `strftime` hay `datetime.now()` không múi giờ (`tests/core/test_conventions.py`).

| Loại | Lưu | Qua API | Người đọc |
|---|---|---|---|
| **Thời điểm** | `timestamptz` (UTC) | RFC 3339 UTC có `Z`, tròn giây: `2026-10-21T03:20:54Z`. Không bao giờ `+07:00` | `HH:mm` theo **múi giờ doanh nghiệp** (`tenant.timezone`), không theo trình duyệt hay máy chủ; kèm ngày `dd/mm` (`dd/mm/yyyy` nếu khác năm hiện tại của doanh nghiệp); rê chuột hiện đầy đủ |
| **Ngày lịch** | `date` | `YYYY-MM-DD` | `dd/mm` theo cùng quy tắc năm |
| **Giờ trong ngày** | **Không lưu thành chữ.** Đọc từ một thời điểm theo múi giờ doanh nghiệp | Không có trường riêng | `HH:mm` |
| **Thời lượng** | Số nguyên theo đơn vị nhỏ nhất, tên trường mang đơn vị | Số nguyên | "20 giờ", "2 ngày" |
| **Tiền** | Đồng, số nguyên | Số nguyên | `2.500.000đ` |
| **Cho mô hình đọc** | | | `YYYY-MM-DD HH:mm` theo giờ doanh nghiệp (mô hình không được thấy UTC) |

Hệ quả:
- **Giờ học thử có một nguồn:** `valid_until`. Ngày và giờ AI nói với khách, và validator dùng để kiểm, đều đọc từ đó; chữ `ngay`/`gio` gõ cạnh bị bỏ qua (test `tests/booking`, `tests/guard`).
- **"Hôm nay" là ngày của doanh nghiệp** cho mọi số chủ đọc: ngân sách theo ngày, việc sáng nay, báo cáo tuần (trước đây ngân sách tính theo nửa đêm UTC, tức 07:00 sáng giờ Việt Nam).
- Thêm trường thời gian mới thì đi qua `wire` / `wire_date`; `tests/console/test_contract.py` duyệt mọi phản hồi của console và từ chối kiểu lạ.

---

### 5.14 Nhật ký hoạt động (2026-10-21)

Một bảng `audit_event` ghi **mọi việc người làm** trong console và mọi lần đăng nhập, để truy vết khi có sự cố. Việc AI làm lúc chạy (gọi công cụ, soạn nháp) vẫn nằm ở `action_log`/`decision_log`; không ghi trùng.

- **Ghi gì:** thời điểm, người (`staff:<tên>`, `key:<tên>`, `system:cli`, `unknown`), vai trò, nhóm (`auth`, `access`, `view`, `data`, `config`, `control`), hành động, kết quả (`success`/`denied`/`failed`), đối tượng (loại, id, nhãn), tóm tắt tiếng Việt, **IP, trình duyệt, mã yêu cầu, mã phiên**, và cột **`metadata` JSONB** cho dữ liệu đi kèm: trước/sau của một lần sửa (`changes`), bản chụp để khôi phục, lý do từ chối, dấu vân tay khoá đã thử.
- **Đăng nhập thất bại:** ghi lý do (`unknown_key`/`revoked`/`wrong_role`) và `attempted` = `fp:` + 10 ký tự băm của khoá. **Không bao giờ ghi khoá đã nhập** (người gõ nhầm hay dán nhầm một khoá thật). Hệ thống đăng nhập bằng khoá API nên không có "tên đăng nhập": dấu vân tay + nhãn nhân viên của khoá (nếu khoá có thật) là phần truy vết. Khoá lạ không thuộc doanh nghiệp nào nên ghi ở cấp nền tảng (`tenant_id` NULL), không tenant nào đọc được.
- **Không ghi:** nội dung tin nhắn, nội dung nháp, khoá hay mật khẩu (khoá tên `secret/token/api_key/key/password` bị che `***` trong mọi `metadata`). Gửi tin chỉ ghi độ dài. Mở một hội thoại là một sự kiện (gộp trong 15 phút).
- **Chống sửa:** chỉ cấp `SELECT, INSERT` cho `cl_app`; trigger chặn `UPDATE/DELETE` cả với owner; mỗi dòng mang `hash = sha256(prev_hash + nội dung)` theo từng tenant (khoá advisory để chuỗi không rẽ nhánh). `GET /audit/verify` và `dev audit-verify` tính lại chuỗi. **Giới hạn thật:** superuser vẫn có thể `TRUNCATE` hoặc tắt trigger; chuỗi băm giúp *phát hiện* sửa giữa chừng, không phát hiện cắt đuôi. Muốn chặn hẳn thì neo mã băm cuối ngày ra ngoài (chưa làm).
- **Ai xem:** chủ xem toàn bộ, lọc theo người, xuất CSV (có chặn công thức `=,+,-,@`); nhân viên chỉ xem dòng của chính mình. IP ghi nguyên (theo yêu cầu); chỉ tin `X-Forwarded-For` khi `TRUST_PROXY_HEADERS=true`.
- **Phân trang thật:** trang + cỡ trang trong `{10,20,50,100}`, trả `total`/`pages`.
- **Còn mở:** thời hạn giữ 12 tháng (cấu hình) chưa có job xoá; dòng cũ hơn hạn sẽ phải xoá bằng owner có chủ đích (trigger chặn), nên cần một đường lưu trữ riêng trước khi bật.

### 5.15 Đăng nhập, phiên và phân quyền của console (2026-10-21)

Console không còn đăng nhập bằng khoá API. Khoá API chỉ còn cho máy gọi máy (`/review`, `/supervisor`, trang `/staff` cũ).

- **Tài khoản:** `app_user` (email duy nhất toàn hệ thống, vì email là thứ tìm ra doanh nghiệp; vai trò `owner`/`staff`/`teacher`; `staff_ref` duy nhất trong doanh nghiệp và là tên nhân viên ghi trên nháp và nhật ký). Chỉ khoá (`disabled`), không xoá, vì nhật ký trỏ tới họ. RLS `FORCE`; riêng việc "tìm người theo email trước khi biết doanh nghiệp" dùng một policy chỉ cho đúng một dòng khớp `app.login_email` (tương tự `app.session_id` cho phiên), nên không có bảng nào bỏ RLS.
- **Mật khẩu:** scrypt (thư viện chuẩn, `N=2^15`), muối riêng mỗi mật khẩu, tham số lưu cùng hash. Luật: 10–128 ký tự, có chữ và số/ký tự đặc biệt, không phải mật khẩu phổ biến, không chứa email hay tên. Không bao giờ ghi vào nhật ký, API hay log. Người lạ và người có tài khoản nhận cùng một câu trả lời và cùng thời gian (luôn băm một lần), nên không dò được email nào có thật.
- **Chống đoán mật khẩu:** `login_throttle` (khoá băm): 5 lần sai cho một email thì khoá 15 phút, 30 lần sai từ một địa chỉ trong 10 phút thì khoá địa chỉ. Khoá áp cả cho email không tồn tại (không lộ gì). Trong lúc khoá, ngay cả mật khẩu đúng cũng không được xét. Đổi mật khẩu sai mật khẩu hiện tại tính vào cùng bộ đếm. Đăng nhập đúng xoá bộ đếm của email.
- **Phiên: access token + refresh token (2026-11-06, migration 0047-0048):** hai cookie HttpOnly, SameSite=Strict, Secure khi https. **Access token** (`cl_session`) là JWT HS256 sống **15 phút** (`ACCESS_TOKEN_MINUTES`), `alg` được ghim; server không lưu nó, chỉ kiểm tra chữ ký. Nó mang người (`sub`), lần đăng nhập (`sid`), **phiên bản** (`ver`), doanh nghiệp, vai trò, tên và múi giờ, nên một request không phải đọc DB. **Refresh token** (`cl_refresh`, dạng `<sid>.<bí mật>`, **mờ**, không phải JWT) sống **7 ngày** kể từ lần dùng cuối (`REFRESH_TOKEN_DAYS`) và chỉ được gửi tới `/api/v1/session` (cookie `Path`), không bao giờ tới phần còn lại của API; DB chỉ giữ **băm** của bí mật. Khi access token hết hạn, trang gọi `POST /session/refresh` (một lần, các request lỗi cùng lúc chờ chung kết quả) và nhận cả access token mới lẫn refresh token mới. **Mỗi lần dùng, refresh token bị đổi** (xoay vòng): hạn mới = 7 ngày nữa nhưng không bao giờ vượt hết đăng nhập (`SESSION_ABSOLUTE_HOURS`, 30 ngày). Mã cũ xuất hiện lại trong 10 giây là hai tab đua nhau, chỉ cấp access token; sau 10 giây là **hai người cùng giữ một mã** nên cả đăng nhập đó bị kết thúc và ghi `refresh.reused`. Một mã sai bí mật nhưng đúng `sid` chỉ bị từ chối, không kết thúc gì (`sid` không phải bí mật, nằm trong access token). Mỗi lần làm mới còn đọc lại người dùng nên tên, vai trò, múi giờ không cũ quá 15 phút, và tài khoản bị khoá không làm mới được. **Redis chỉ giữ `user id → version`** (`auth/versions.py`, khoá `cl:v:<người>`, hạn riêng 5 phút), một lệnh `GET` mỗi request; nguồn sự thật là `app_user.token_version`, Redis chết thì mọi request hỏi DB. **Quy tắc thu hồi duy nhất:** access token cùng version thì đi qua; ở version **cũ hơn** thì DB được hỏi một câu — đăng nhập đó (`auth_session.revoked_at`) và tài khoản còn hiệu lực không? Còn thì đổi lấy token version mới, hết thì 401. Nhờ vậy đăng xuất mọi nơi (đổi mật khẩu, khoá, đổi vai trò vì vai trò nằm trong token, đổi email, hoặc nút «đăng xuất mọi thiết bị») đánh dấu mọi dòng `auth_session` rồi tăng version, còn **đăng xuất một thiết bị** đánh dấu đúng dòng đó rồi tăng version: thiết bị đó chết ở request kế tiếp (cả refresh token của nó) còn các thiết bị khác được cấp token mới một lần. Đăng xuất chỉ cần refresh token cũng được, nên người đã hết access token vẫn đăng xuất hẳn được. `auth_session` còn là danh sách thiết bị. CSRF là HMAC của `sid`, nên token đổi không làm hỏng mã của trang. Phản hồi `/api` có `Cache-Control: no-store`; mọi phản hồi có `X-Frame-Options: DENY`, `nosniff`.
- **Không có mật khẩu tạm (2026-11-06, migration 0045):** chủ thêm người thì tài khoản được tạo **không có mật khẩu dùng được** (`password_hash = '!'`, không phải băm của gì nên không giá trị nào khớp) và hệ thống gửi **thư mời** chứa liên kết một lần (token ngẫu nhiên, DB chỉ giữ băm, nằm trong fragment, hạn `INVITE_LINK_HOURS`=72 giờ); người đó mở liên kết, tự chọn mật khẩu rồi đăng nhập. Không gửi thư được (thiếu SMTP hoặc `PUBLIC_BASE_URL`) thì **không tạo được tài khoản** — không có đường lui sang mật khẩu sinh sẵn. Chủ cũng chỉ gửi *liên kết* đặt lại (`POST /team/{id}/send-link`), không bao giờ thấy hay đặt mật khẩu của ai. Dùng liên kết hoặc đổi mật khẩu kết thúc mọi phiên khác. Chủ quên mật khẩu và không có thư: `cli reset-password` hỏi mật khẩu mới ở terminal (người vận hành máy chủ).
- **Luật không khoá mình ra ngoài:** luôn còn ít nhất một chủ đang hoạt động; không ai tự đổi vai trò, tự khoá, tự đặt lại mật khẩu của chính mình ở trang quản lý.
- **Phân quyền:** `auth/perms.py` là bảng duy nhất vai trò → quyền (`inbox.use`, `skills.manage`, `team.manage`, …). Giáo viên chỉ chạm lớp được giao (`class_teacher`, `console/scope.py`, WP46). Endpoint khai `need("quyền")`, hoặc `need_class("quyền")` khi đường dẫn trỏ tới đồ của một lớp; thiếu quyền là 403 `FORBIDDEN` và có dòng `permission.refused` trong nhật ký. Test `test_every_endpoint_has_been_given_a_decision` buộc mọi endpoint mới phải được xếp "chỉ chủ" / "ai đăng nhập cũng được" / "công khai". `/session` trả danh sách quyền để giao diện ẩn nút; máy chủ vẫn kiểm mọi lời gọi.
- **Nhật ký:** `login.ok/failed` (lý do `unknown_email`/`bad_password`/`disabled`, email đã gõ nếu trông như email, **không bao giờ** mật khẩu), `logout`, `logout.all`, `session.revoked`, `password.changed/change_failed/reset`, `user.created/updated`, `permission.refused`, `csrf.refused`.
- **Quên mật khẩu qua email (2026-11-02):** `POST /api/v1/auth/forgot` (công khai) luôn trả cùng một câu trả lời, phần tra tài khoản và gửi thư chạy **sau** khi trả lời nên thời gian không lộ email nào có thật. Giới hạn: 3 thư/giờ cho một email (quá thì im lặng), 10 yêu cầu/giờ cho một địa chỉ (quá thì 429). Token 32 byte ngẫu nhiên nằm trong **fragment** của liên kết (`/app/reset#token=…`, không tới log máy chủ hay header Referer), bảng `password_reset` chỉ giữ băm SHA-256, hạn 30 phút, dùng một lần, yêu cầu mới huỷ liên kết cũ. `POST /api/v1/auth/reset` theo luật mật khẩu ở trên, kết thúc mọi phiên của người đó, gỡ khoá đoán sai của tài khoản, ghi `password.reset_by_email` (không token, không mật khẩu). Liên kết dựng từ `CL_PUBLIC_BASE_URL`, không bao giờ từ Host của request. Thư không chứa mật khẩu. Tính năng chỉ bật khi có `CL_PUBLIC_BASE_URL` và một đường gửi thư (`CL_SMTP_HOST` + `CL_MAIL_FROM`, hoặc `CL_MAIL_DIR` để ghi thư thành tệp khi phát triển); chưa bật thì trang đăng nhập giữ lời dặn cũ. Mô-đun `notify/mailer.py` (mọi lời gọi mạng ra ngoài chỉ nằm trong `notify/`, `outbound/`, `llm/`, `connectors/`, `cells/`: có test chặn).
- **Xác thực 2 lớp (2026-11-09, migration 0049):** mỗi người **tự bật** ở Tài khoản, **không bắt buộc** với ai. TOTP (RFC 6238, HMAC-SHA1, 6 số, bước 30 giây, lệch ±1 bước), tự viết bằng thư viện chuẩn như scrypt, cùng **10 mã dự phòng** dùng một lần. Khoá TOTP lưu mã hoá Fernet (cùng khoá với số CCCD), mã dự phòng chỉ lưu bản băm; mã TOTP đã dùng không dùng lại được (lưu bước thời gian cuối). Bật qua hai bước: `setup` (cần mật khẩu) tạo khoá chờ, `enable` (cần một mã sinh từ khoá đó) mới bật và trả mã dự phòng một lần; QR vẽ ngay trong trình duyệt. Đăng nhập: đúng mật khẩu mà đã bật thì **chưa có phiên**, server đặt cookie thử thách ký riêng `cl_mfa` (5 phút, gắn người và `token_version`), `POST /session/mfa` với mã đúng mới tạo phiên. Mã sai đếm vào khoá riêng (`mfa:<user>`, cùng ngưỡng với mật khẩu) ở cả bước đăng nhập lẫn trang Tài khoản. Tắt hoặc tạo lại mã dự phòng cần mật khẩu và một mã đang dùng. Đặt lại mật khẩu qua email không bỏ qua bước mã. **Mất điện thoại:** dùng mã dự phòng; chủ tắt được cho nhân viên và giáo viên (nhập mật khẩu của chính chủ, người kia bị đăng xuất mọi thiết bị và nhận thư báo, chủ không thấy khoá hay mã nào: người đó tự bật lại trên máy mình); MFA của một chủ khác chỉ người vận hành tắt được (`cli reset-mfa --email`). Nhật ký: `login.mfa_failed`, `mfa.enabled/disabled/disabled_by_owner/recovery_renewed/reset`, `login.ok` có `mfa: totp|recovery`; không bao giờ ghi khoá hay mã.
- **Chưa làm:** thời hạn đổi mật khẩu định kỳ (khuyến nghị hiện nay là không ép); passkey (WebAuthn).

### 5.16 Trang quản trị nền tảng (2026-11-09, WP47)

Người vận hành máy chủ cần làm những việc không thuộc doanh nghiệp nào: mở doanh nghiệp mới, cứu một chủ bị khoá, dừng AI khi có sự cố. Trước đây các việc này phải SSH vào máy chủ chạy `cli`. Trang `/app/admin` thay cho phần đó.

- **Tách hẳn khỏi console của doanh nghiệp.** Không có vai trò `admin` trong `perms.ROLE_PERMS`. Bảng riêng `platform_admin` (không `tenant_id`), API riêng `/api/admin`, cookie riêng `cl_admin` (HttpOnly, SameSite=Strict, `Path=/api/admin`), khoá ký riêng. Một lỗi phân quyền ở console doanh nghiệp không mở được trang này, và ngược lại.
- **Bắt buộc xác thực 2 lớp.** Đúng mật khẩu chỉ cho một cookie thử thách 5 phút. TOTP được cài ngay trong `cli create-admin` (trên máy chủ), nên web không có bước cài và không có lúc nào chỉ mật khẩu là đủ. Đếm sai dùng chung `login_throttle`.
- **Phiên ngắn, thu hồi ngay.** JWT sống 30 phút kể từ request cuối (làm mới khi còn dưới một nửa), tối đa 8 giờ từ lúc đăng nhập. Mỗi request đọc lại dòng `platform_admin` (trạng thái, `token_version`). Đăng xuất tăng version nên mọi thiết bị của admin đó đều ra.
- **Bước xác nhận lại:** tắt 2 lớp của một người, và dừng AI toàn hệ thống, cần mã TOTP đang hiện của admin.
- **Thấy gì:** tên, múi giờ, số sandbox và trạng thái, tài khoản của doanh nghiệp (email, tên, vai trò, trạng thái, 2 lớp bật hay tắt, lần đăng nhập cuối). **Không** thấy hội thoại, khách, SĐT, CCCD, catalog. Truy cập dữ liệu khách để hỗ trợ (break-glass) chưa làm, thuộc nhóm C.
- **Sửa tên và email tài khoản** (2026-11-10): sửa lỗi gõ email của chủ vừa mời thì gửi lại thư mời tới địa chỉ mới, liên kết cũ hết hiệu lực. Đổi email của tài khoản *đang dùng* là đường chiếm tài khoản (đổi email rồi gửi liên kết đặt lại), nên cần mã TOTP của admin, đăng xuất người đó mọi nơi và báo về địa chỉ cũ. Vai trò, trạng thái và thông tin cá nhân vẫn do chủ doanh nghiệp sửa.
- **Không mật khẩu tạm:** như §5.15, admin chỉ gửi liên kết qua email. Máy chủ chưa có thư thì vẫn dùng `cli create-user --password` / `cli reset-password`.
- **Nhật ký:** thao tác lên một doanh nghiệp ghi vào chuỗi của doanh nghiệp đó (`actor=admin:<email>`, `role=platform`), nên chủ thấy ai đã làm gì với tài khoản của mình. Đăng nhập admin ghi ở phạm vi nền tảng.
- **Chưa làm (P1/P2):** sức khoẻ worker và job, outbox, khoá API cho bridge, đẩy skill mẫu, kiểm toàn vẹn nhật ký hàng loạt, giới hạn IP, quản lý admin qua giao diện.

---

## 6. Ràng buộc pháp lý và kênh

Tra từ web 2026-10-09/10, **chưa có luật sư xác nhận.**

- **Luật AI 134/2025, Điều 11** (hiệu lực 1/3/2026): phải công khai cho người dùng biết họ đang nói với AI. Cấm persona giả làm người.
- **Luật BVDLCN 91/2025 + NĐ 356/2025:**
  - đồng ý phải rõ ràng, kiểm chứng được, ghi theo khách × kênh × mục đích;
  - Cortex là bên xử lý, phải có DPA;
  - gọi LLM ở nước ngoài = chuyển dữ liệu xuyên biên giới (Điều 20), phạt tới 5% doanh thu → **che PII trước khi gọi LLM**.
- **NĐ 91/2020:** tin quảng cáo cần đồng ý trước. Khách từ chối hoặc không phản hồi thì không gửi tiếp.
- **Y tế:** tư vấn chẩn đoán / điều trị = khám chữa bệnh từ xa.
- **Messenger:**
  - nhắn tự do trong 24 giờ;
  - HUMAN_AGENT trong 7 ngày, chỉ cho người gõ tay;
  - Marketing Messages: opt-in, 1 tin/người/ngày, trả phí, có ở VN;
  - Recurring Notifications đã ngừng (10/2/2026);
  - đọc hội thoại trực tiếp cần Advanced Access + pháp nhân.
- **Pancake Public API:**
  - token page không hết hạn, **toàn quyền**, không có chế độ chỉ đọc;
  - 5 req/s mỗi page;
  - **không có endpoint lịch hẹn**;
  - webhook tốn slot, tự tắt khi lỗi > 80%.
- **Zalo OA:** cần gói Tăng trưởng trở lên, tối đa 3 app uỷ quyền. Tin tư vấn trong khoảng 48 giờ. ZNS dùng mẫu đã duyệt. *Chưa xác minh từ nguồn chính thức.*
- **Zalo cá nhân:** không có API. Chỉ nhắc nhân viên.

---

## 7. Kế hoạch và lộ trình xây

### 7.1 Cổng sản phẩm và tầng nền tảng

| Cổng | Hạn | Phải đạt | Nền tảng được xây | Không đạt thì |
|---|---|---|---|---|
| **G0 — Chọn ngành** | 2026-10-16 | Ngành ghi vào 2.3 + danh sách ≥ 15 chủ doanh nghiệp + tên người giữ mốc | **v0** (§7.2), trong ngân sách L3 | Mặc định khoá học / du học |
| **G1 — Tiếp cận** | 2026-10-23 | H0; ≥ 3 doanh nghiệp cho xem inbox | v0 đạt nghiệm thu A–D (§7.2) | **Ngừng mọi code mới** (chỉ sửa lỗi) cho tới khi đạt. Thử ngành thứ hai đúng một lần |
| **G1.5 — Nỗi đau** | 2026-11-15 | H1, H2, H3 qua ngưỡng | Chỉ sửa lỗi và cải tiến *đo được* trên v0 | **Dừng hướng** |
| **G2 — Tiền** | 2026-12-31 | H4: ≥ 3 khách chuyển khoản ≥ 2 triệu/tháng; ≥ 5 lịch hẹn/tháng/khách truy được về danh sách đã gửi | **Mở T1** | Portfolio (L6) |
| **G2.5 — Việc thứ hai** | — | ≥ 2 khách đang trả tiền tự nêu một việc thứ hai trong `docs/customers/` và chịu trả thêm | Sandbox thứ hai (ví dụ `owner_digest`); trigger cron/condition dùng LLM; AI tổng (chỉ đọc metadata) | Ở lại sản phẩm đơn |
| **G3 — Lặp lại** | 2027-02-28 | ≥ 6 khách; phần làm tay đã lặp ở ≥ 5 khách | Form skill cho chủ / agency; connector `http_readonly` | Giữ dạng dịch vụ |
| **G4 — Sống được** | 2027-03-31 | ≥ 10 khách, ≥ 30 triệu/tháng, churn ≤ 8%/tháng, ≥ 1 agency mang về ≥ 3 khách | T2: MCP bên ngoài (chỉ đọc), chiều ngược về kênh, thẻ chiến lược | Portfolio (L6) |

### 7.2 v0 — "sẵn sàng chạy thật" (ngân sách ≤ 5.000 dòng)

**Đầu ra của v0 là chạy thật được** với doanh nghiệp đầu tiên ở G1.5. v0 bàn giao:

1. Hệ thống chạy trọn **kịch bản chuẩn** trên bộ chạy thử (§5.12), có script chạy lại được.
2. **Checklist thiết lập một doanh nghiệp** trong ≤ 2 giờ.
3. **Báo cáo chạy thử với LLM thật** (≈ 30 hội thoại thử, các số ở nhóm B).
4. Test xanh, CI xanh, README / DESIGN / PLAN / REVIEW cập nhật.

**Nghiệm thu: phải đạt cả bốn nhóm.**

**A. Chức năng** (mỗi dòng có test hoặc chạy được trong kịch bản chuẩn)

| # | Phải làm được |
|---|---|
| A1 | Nhận tin **thật** từ Facebook Page thử; phân biệt đúng khách / nhân viên / bot |
| A2 | Phát hiện khách im và khách tới ngày hẹn |
| A2b | Khách nhắn mà chưa ai trả lời → sau khi khách nhắn xong ≤ 60 giây có trả lời (auto) hoặc nháp trả lời (manual); nhân viên đang trực thì AI không chen ngang (WP16) |
| A3 | Soạn nháp có nguồn cho mọi con số; giá bịa bị chặn |
| A4 | Ghi trí nhớ có bằng chứng: ngày hẹn, người quyết định, đã gọi, đã chốt; tự đóng lời hẹn khi có kết quả |
| A5 | Deal "Won" trong Twenty (và đơn từ Google Sheet) → `deal.updated` → đóng hẹn, thôi theo sát |
| A6 | Chế độ **manual**: nhân viên duyệt trên trang duyệt → hệ thống gửi qua bridge. Chế độ **auto**: tự gửi khi được phép, còn lại tự rơi về manual |
| A7 | Số liệu của AI tổng không chứa chữ nào của khách |
| A8 | Thêm skill mới chỉ bằng file; thêm lĩnh vực mới chỉ bằng domain pack |

**B. Chất lượng** (≈ 30 hội thoại thử, LLM thật, người xây và tester đóng vai khách theo nhiều kịch bản)

| Chỉ số | Ngưỡng |
|---|---|
| Nháp bịa giá / dữ kiện lọt tới khách | **0** |
| Nháp dùng được (gửi nguyên văn hoặc sửa nhẹ) | ≥ 70% |
| Ca nên im (đã chê giá, đã mua) mà hệ thống im đúng | ≥ 90% |
| Ngày hẹn ghi đúng trong ca hẹn rõ | ≥ 90%, **0 ngày bịa** |
| Tên / SĐT lọt vào nội dung gửi LLM | **0** |
| Trigger → nháp (p95) | ≤ 60 giây |
| Trả lời lượt khách: AI chen ngang khi nhân viên đang trực | **0** |
| Trả lời lượt khách dùng được (đúng ý, đúng catalog) | ≥ 80% |
| Chi phí LLM mỗi nháp | ≤ 100đ |

Không đạt nhóm B sau 2 vòng chỉnh skill và prompt → xem lại cách làm (ví dụ mẫu câu cố định thay vì để LLM viết tự do), không cố đẩy tiếp.

**C. An toàn và pháp lý** (bắt buộc trước khi chạm dữ liệu khách thật — §10): repo private · server cũ vá hoặc tắt · DPA mẫu có luật sư xem · nhà cung cấp LLM không dùng dữ liệu để huấn luyện · kill switch thử được (< 1 phút) · backup DB hằng ngày · đường kết nối khách thật đã rõ (qua Pancake, hoặc pháp nhân + App Review).

**D. Kỷ luật:** ≤ 5.000 dòng; L8 không vi phạm hai tuần liên tiếp.

**Sang G1.5 khi:** v0 đạt A + B + C, **và** cổng kinh doanh G1 đạt. v0 đạt mà G1 trượt thì vẫn không sang được.

**Đợt 1 (đã xong, 2026-10-10):** WP0–WP7 — nền tảng tối thiểu, 175 test, 2.810 dòng.

**Đợt 2 — gói việc để chạy thật** (Sonnet thực thi, leader điều phối và review; thứ tự do tệp dùng chung quyết định):

| Sóng | Gói | Nội dung | Dòng ước tính |
|---|---|---|---|
| 0 | **WP12 Nền** | Migration 0002 cho **mọi** bảng/cột mới của đợt 2 (`contact_fact`, `deal`, `outbox`, `sandbox.send_mode`, `sandbox.domain_pack`, `connector.outbound`, trạng thái `booked`); **domain pack** (từ vựng ra khỏi lõi, sự kiện trung tính `conversation.*`) | ~200 |
| 1 | **WP9 Trí nhớ** | Fact có bằng chứng, vòng đời lời hẹn, kết quả (won/booked/lost), `deal.updated`, API nhân viên ghi và sửa trí nhớ | ~410 |
| 1 | **WP10 Bridge Messenger** | Chiều vào (chữ ký, xác minh webhook, `is_echo`/`app_id`) + chiều ra (nhận Cortex Action Format, thi hành luật Messenger, gọi Send API) | ~280 |
| 1 | **WP11 Bộ chạy thử** | Bridge Twenty → `deal.updated`, import catalog và đơn từ Google Sheet, `dev/` compose + script kịch bản chuẩn | ~150 (+ dev) |
| 1 | **WP13 Trang duyệt** | Trang web nhỏ dùng được trên điện thoại: danh sách cần duyệt, Duyệt / Sửa / Bỏ, ghi nhanh trí nhớ | ~300 |
| 2 | **WP8 Gửi tin** | `send_message` + outbox + worker chiều ra, chế độ auto/manual theo sandbox và skill, tự rơi về manual, xếp hàng ngoài giờ, dòng xưng AI | ~550 |
| 2b | **WP16 Lượt khách** | Gom tin theo lượt (`reply_check_at`), sự kiện `conversation.awaiting_reply`, skill `tra-loi-khach`, act `reply/wait/handoff/none`, không chen ngang nhân viên, worker chạy liên tục | ~220 |
| 3 | **WP14 Nghiệm thu** | Chạy kịch bản chuẩn trên bộ thử, đo nhóm B với LLM thật, checklist thiết lập | test + báo cáo |

Tổng ước tính ≈ 2.810 + 1.890 ≈ **4.700 / 5.000**.

**Không thuộc v0:** AI tổng chạy LLM · sandbox thứ hai · form skill cho chủ · MCP bên ngoài · multi-cell · bridge cho phần mềm cụ thể của khách (KiotViet, Sapo… — làm sau G1 khi biết khách dùng gì) · thông báo qua Telegram/Zalo (v0 dùng trang duyệt).

**Tuần này, song song với việc xây:**

- vá bảo mật (§10);
- phỏng vấn cho G1;
- tạo page Pancake thử để xác minh API.

### 7.3 Xây toàn bộ roadmap trong lúc tìm khách (từ 2026-10-17)

Thứ tự theo **mức chặn việc nhận khách thật**, rồi tới độ phụ thuộc kỹ thuật. Mỗi gói vẫn cần phiếu / manifest (L7) trước khi code, và ghi giờ code vào §9 (L8).

| Đợt | Gói | Nội dung | Trạng thái 2026-10-17 |
|---|---|---|---|
| 1 | **WP14 Page thật** | Bridge Pancake / Messenger trên Page thử, xác minh R13/R27, đo nhóm B ~30 hội thoại | ⏳ **Cần tài khoản + Page thử**, code không tự làm được |
| 1 | **Vận hành** | Kill switch < 1 phút, backup DB hằng ngày, checklist thiết lập ≤ 2 giờ, gitleaks pre-commit | ⏳ Chưa làm (nhóm C) |
| 2 | **WP17 + WP18** | Thông báo đẩy (R58); AI giữ chỗ học thử, phiếu đăng ký là dòng catalog | ✅ Xây xong, test giả lập |
| 3 | **WP19 + WP20** | Cron mẫu (`morning_list`, `weekly_digest`), sandbox `owner_digest`; connector `http_readonly` | ✅ |
| 4 | **WP21** | AI tổng: tín hiệu 0 token → đề xuất → chủ duyệt; tóm tắt tuần do LLM viết từ số | ✅ |
| 5 | **WP22** | Form skill (mẫu cố định, không tự gửi) + shadow thật | ✅ |
| 6 | **WP23–26** | MCP ngoài chỉ đọc có ghim; `add_tag`/`add_note`; thẻ chiến lược; multi-cell | ✅ Lõi xong; chưa bridge nào thi hành nhãn/ghi chú (R82) |
| UI | **WP27 Console** | Giao diện chính cho chủ/nhân viên (`cortex-leads/web/`, thiết kế `pencil/`): Hộp thư, Kỹ năng, Sandbox, AI tổng, Dừng khẩn cấp | ✅ 5 màn, chưa có Việc hôm nay / Dữ liệu / Báo cáo / Cài đặt (R85–R90) |

Chi tiết từng gói và bất biến nó giữ: [`cortex-leads/PLAN.md`](../cortex-leads/PLAN.md) §9. Rủi ro còn mở: REVIEW R70–R84.

**Vẫn không làm** (§11): người dùng tự gắn MCP, adapter từng kênh trong lõi, bot Zalo cá nhân, AI tổng đọc văn bản, `$or` / biểu thức trong trigger.

**Mốc giết thay cho đóng băng:** trượt G1 (2026-10-23) → dừng mọi code mới, chỉ sửa lỗi, thử ngành thứ hai đúng một lần (§7.1).

---

## 8. Cam kết hành vi

| Cam kết | Đo bằng |
|---|---|
| 10 giờ/tuần nói chuyện với chủ doanh nghiệp hoặc nhân viên trong ngành | Số file mới trong `docs/customers/` |
| Giờ code ≤ giờ nói chuyện với khách (L8) | Ghi ở §9 |
| ~~Không viết code ngoài v0 trước G2 (L3)~~ — bỏ 2026-10-17; thay bằng: trượt G1 thì dừng code mới | `git log` |
| Chỉ tính tiền thật | Chuyển khoản |

**Người giữ mốc:** *(điền tên trước 2026-10-16)*

---

## 9. Rà soát hằng tuần

| Tuần | Cổng | Cuộc nói chuyện mới | Giờ code / giờ khách | Dòng v0 / 4.000 | Phát hiện quan trọng nhất | Vi phạm L3 / L8 | Người giữ mốc xác nhận |
|---|---|---|---|---|---|---|---|
| 2026-10-09 | G0 | 0 | — | 0 | — | — | — |
| 2026-10-10 | G0 | 0 | v0 xây xong (175 test) | 2.810 / 4.000 | R13, R15 cần quyết (xem cortex-leads/REVIEW.md) | — (v0 trong phạm vi L3 sửa đổi) | — |
| 2026-10-12 | G0 | 0 | Đợt 2 xây xong tới WP8 + F1, F2 (327 test; kịch bản chuẩn giả lập chạy trọn, gồm auto/manual) | 4.627 / 5.000 | Còn WP14 (cần Page thật, API key); R13/R27 phải kiểm trên Page thật | Chưa có cuộc nói chuyện nào với khách — L8 bắt đầu tính từ 17/10 | — |
| 2026-10-14 | G0 | 0 | **Khép giai đoạn xây + thử local.** WP15 (giọng văn), F3, WP16 (trả lời lượt khách); nhập vai auto với LLM thật trên kênh giả + dữ liệu mẫu đầy đủ: 16/16 tin được đáp, 12 tự trả lời; 371 test | 4.943 / 5.000 | Chưa đạt A1 (Page thật), nhóm B (chưa đo ~30 hội thoại; demo lộ 2 lỗi dữ kiện đã sửa: hoàn phí do dữ liệu mơ hồ, chữ Trung), nhóm C (repo công khai, server cũ, DPA, backup). R58 thông báo đẩy cần quyết | Chưa có cuộc nói chuyện nào với khách — G0 hạn 16/10, L8 tính từ 17/10 | Phase kế: WP14 Page thật + đo nhóm B; phỏng vấn G1; code đóng băng trừ sửa lỗi khi chạy thật |
| 2026-10-17 | G0 | 0 | **Bỏ L3, xây đợt 2–6** (một ngày, 497 test); L8 bắt đầu tính hôm nay | ≈ 7.990 (không còn trần) | Hệ thống rộng hơn nhiều nhưng **vẫn 0 cuộc nói chuyện với khách và 0 bằng chứng**: rủi ro lớn nhất không phải kỹ thuật. Mốc G1 23/10 vẫn là mốc giết | **L8: giờ code ≫ giờ khách trong tuần này** (ghi đỏ). Nếu tuần tới vẫn vậy, L8 yêu cầu dừng code | Chưa có |

---

## 10. Nợ phải trả

**Bảo mật server cũ — khẩn** (đã xác minh trong code; trạng thái thật trên server chưa kiểm):

- [ ] **Security Group trên AWS:** đóng `5434` (Postgres `cortex/cortex`), `6377` (Redis không có mật khẩu), `8000` (API, Swagger, `/internal/*`), `20128` (9Router). Docker tự ghi iptables nên `ufw` không chặn được các cổng này.
- [ ] Compose: bind các cổng về `127.0.0.1`, đổi mật khẩu DB, thêm `requirepass` cho Redis.
- [ ] Đổi `SECRET_KEY` và `INTERNAL_API_KEY`. Giá trị cũ nằm trong repo công khai nên coi như đã lộ. Refresh token Google được mã hoá bằng khoá suy ra từ `SECRET_KEY`, phải xử lý trước khi đổi.
- [ ] Ứng dụng phải báo lỗi khi khởi động nếu secret là giá trị mặc định. Tắt `/register` và Swagger.
- [ ] Kiểm tra dấu vết xâm nhập. Hoặc dump DB rồi tắt server cũ.

**Trước khi nhận token hoặc dữ liệu của doanh nghiệp đầu tiên:**

- [ ] `cortex-leads/` (hoặc cả repo) chuyển sang private.
- [ ] Hợp đồng lao động: kiểm điều khoản cạnh tranh và sở hữu trí tuệ.
- [ ] Pháp nhân.
- [ ] DPA tối giản, có luật sư xem.
- [ ] Kho dữ liệu mã hoá, có hạn xoá. Tài khoản Pancake riêng có 2FA, có sổ ghi truy cập.
- [ ] Pre-commit gitleaks + regex số điện thoại.

**Phải xác minh bằng tay:**

- [ ] Gửi qua Pancake ngoài 24 giờ: có tự gắn tag HUMAN_AGENT không? `can_inbox` có đúng không? Gửi tin cần gói Pancake nào?
- [ ] Nháp do nhân viên bấm gửi dưới tag HUMAN_AGENT có hợp lệ với Meta không.
- [ ] developers.zalo.me: cửa sổ nhắn; 3 slot app uỷ quyền; có chặn IP ngoài Việt Nam không.
- [ ] Một buổi với luật sư: vai trò bên xử lý; chuyển dữ liệu xuyên biên giới; NĐ 142/2026.

---

## 11. Không làm — đưa lại phải kèm lý do mới

| Không làm | Vì sao |
|---|---|
| Định vị sản phẩm là chatbot trả lời 24/7 *thay* nhân viên | Hàng miễn phí. Trả lời lượt khách (WP16) chỉ lấp chỗ chưa có người; điểm bán vẫn là không để rơi + trí nhớ + theo sát (§1.3) |
| ~~Xây nền tảng vượt phạm vi v0 trước G2~~ — **gỡ 2026-10-17** | Rủi ro cũ vẫn còn: bản tái sinh của `workflow_service` / planning-v3. Giữ kỷ luật bằng L1, L7, L8 và mốc giết G1 |
| Sandbox thứ hai trước G2.5 | Chưa có khách nào xin |
| Người dùng tự gắn MCP trước G4 | Tool poisoning; dữ liệu khách |
| Adapter từng kênh trong lõi | Code riêng của kênh nằm ở bridge (§5.2) |
| AI tổng đọc văn bản của sandbox | Phá mẫu Dual-LLM (§5.6) |
| `$or`, biểu thức, chuỗi bước trong trigger / manifest | Đang viết lại workflow DSL |
| Bot nhắn khách qua Zalo cá nhân | Không có API hợp lệ |
| Tư vấn chẩn đoán, điều trị, visa | Pháp lý |
| Bảng xếp hạng nhân viên | Nhân viên sẽ né và chống |
| Kho bộ nhớ chung tìm bằng embedding | Đã đo, không tách được đúng / sai (LESSONS 3) |
| Import code từ `backend/` | Khoá theo `user_id`, có lỗ hổng giả danh. Chỉ port có chủ đích |
| Trợ lý cá nhân / chat agent cho người xây | Đã chết (LESSONS 2) |

---

## Nguồn chính

- Meta Messenger policy: https://developers.facebook.com/docs/messenger-platform/policy/policy-overview · Marketing Messages FAQ: https://developers.facebook.com/documentation/business-messaging/messenger-platform/marketing-messages-on-messenger/faq
- Meta Business AI tại VN: https://vietnamnews.vn/Sci-Tech/1779103/viet-nam-becomes-test-bed-for-ai-driven-commerce-tools.html
- Pancake OpenAPI: https://developer.pancake.biz/openapi/openapi.yaml · Webhook: https://developer.pancake.biz/openapi/webhook.yaml
- Agent Skills spec: https://agentskills.io/specification
- MCP spec 2026-07-28: https://modelcontextprotocol.io/specification/2026-07-28/changelog
- n8n — trigger node phải viết bằng code: https://docs.n8n.io/integrations/creating-nodes/plan/choose-node-method
- Dual-LLM: https://simonwillison.net/2023/Apr/25/dual-llm-pattern/ · CaMeL: https://arxiv.org/abs/2503.18813
- Luật AI 134/2025: https://thuvienphapluat.vn/van-ban/Cong-nghe-thong-tin/Luat-Tri-tue-nhan-tao-2025-so-134-2025-QH15-679013.aspx
- Luật BVDLCN, Điều 20: https://hethongphapluat.com/luat-bao-ve-du-lieu-ca-nhan-2025/dieu-20 · NĐ 356/2025: https://www.ey.com/vi_vn/technical/tax/tax-and-law-updates/nghi-dinh-so-356-2025-nd-cp-quy-dinh-chi-tiet-mot-so-dieu-va-bien-phap-thi-hanh-luat-bao-ve-du-lieu-ca-nhan
