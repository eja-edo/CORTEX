# Cortex — Bài học đã trả giá

**Lập 2026-10-09**, khi khép hướng đi cũ (DESIGN bản 1, lưu ở
[`archive/DESIGN-v1-2026-08.md`](archive/DESIGN-v1-2026-08.md)).

Đây **không phải kế hoạch** và không ràng buộc hướng mới. Nó chỉ ghi lại
những gì đã thử, đã đo, đã chết, và vì sao. Mục đích: hướng mới không phải
trả lại học phí cũ. Một bài học ở đây chỉ được gạch bỏ khi có bằng chứng mới,
không phải vì nó bất tiện.

---

## 1. Bối cảnh bằng số

- 2026-08-24: 95 tài khoản, **94 là tài khoản test**, 1 người dùng thật (chính
  tác giả). Khoảng 84.000 dòng code.
- Tới 2026-10-09, trong repo không có bằng chứng nào cho thấy sản phẩm từng
  được một người thứ hai dùng. Không có ghi chép phỏng vấn người dùng, và phép
  thử A/B cũng chưa có số (chưa kiểm được DB production).
- **Mọi thứ trong repo chưa từng gặp người dùng thật.** Đây là sự thật quan
  trọng nhất của tài liệu này.

## 2. Các hướng đã chết, và chết vì sao

| Hướng | Thời gian | Chết vì |
|---|---|---|
| Trợ lý cá nhân đa năng (`planning-v3`) | trước 2026-08 | Không trả lời được câu "người dùng mở nó lúc nào". Quá nhiều bề mặt, không bề mặt nào đủ tốt để có người dùng |
| `goals` do người dùng tự khai | trước 2026-08 | Thực thể nào bắt người dùng tự khai và tự duy trì thì sẽ rỗng mãi mãi |
| Bot nghe channel Mezon, tự trích lời hứa | 2026-08 | Tập thể trả giá (cho bot vào nghe), cá nhân hưởng lợi (nhắc riêng). Đây là lỗi cấu trúc, code không sửa được. Ngoài ra channel không có ranh giới hội thoại |
| Cortex tự làm biên bản họp, tự trích action item | 2026-08 | Bot họp đã làm khâu này. Cạnh tranh ở khâu trích xuất là chọn trận thua |
| `workflow_service` + Temporal | 2026-07 → 08 | 0 workflow trong DB. Không có nhu cầu nhiều bước nào có thật |
| Notes + Yjs, OCR, STT | 2026-07 → 08 | 1 note, 0 asset. Được xây tử tế nhưng không ai dùng |
| "Attention Gate: nói ít hơn mà đúng hơn" (DESIGN v1) | 2026-08 | **Chưa chết, nhưng chưa bao giờ được kiểm.** Hội đồng phản biện chỉ ra giả thuyết lõi khó đứng (xem mục 4) |
| AI companion: chat, bộ nhớ, `Procedure`, thang can thiệp, model packages | 2026-09 | Đi ngược chính DESIGN v1 (§1.3, §13.4). Xây cho một người dùng duy nhất. Không ai trong công việc mở chat ra để "dạy quy trình" cho bot. Agent có quyền ghi thì tự bịa dữ liệu |

**Kiểu thất bại lặp lại qua mọi hướng ở trên:** xây trước, rồi mới hỏi người
dùng, hoặc không bao giờ hỏi. Mỗi lần hướng đổi, code mới lại được viết trước
khi có một người thật nào chạm vào hướng cũ. Viết luật kỷ luật (P8, cổng A/B,
"DỪNG") không thay được việc đi gặp người dùng. Khi luật trên giấy không ai
giữ, nó còn tệ hơn không có luật, vì nó cho cảm giác đang có kiểm soát.

## 3. Những gì đã đo được (kỹ thuật)

| Phát hiện | Bằng chứng | Hệ quả |
|---|---|---|
| Embedding không tách được bộ nhớ liên quan khỏi bộ nhớ gần nghĩa | 2026-09-10, `gemini-embedding-2-preview`: dải đúng [0.56, 0.73], dải nhiễu [0.39, 0.71]. Văn bản dài "gần" với mọi truy vấn | Chỉnh ngưỡng không cứu được recall. Muốn sửa phải sửa ở tầng dữ liệu (tách trigger ra khỏi phần thân) |
| Thang chấm tự động mù với kiểu hỏng mới | 2026-09-11: một transcript đạt 5/5 vẫn hỏng 4 chỗ khi đọc thật | Phải tự đọc transcript. Thang chấm chỉ là lưới chặn lỗi cũ |
| Dòng cuối của prompt quyết định hình dạng JSON | Gateway không hỗ trợ `response_format` | Phải vẽ shape ra. Gọi tên khoá thì model trả mảng chuỗi |
| Agent có quyền ghi sẽ tự tạo dữ liệu không ai yêu cầu | Người dùng nói "deadline sắp tới, tôi hơi lo", agent tạo 6 task "Create file a.txt". Sau khi vá vẫn còn khoảng 1/4 lượt bịa | Một lần ghi rác làm mất niềm tin nhanh hơn mười câu trả lời hay gây dựng được |
| `attention_log` không ghi vì sao im, và nhánh dedup không ghi gì cả | `attention_gate.py` thoát sớm trước khi ghi | Hiện không đếm được "đã im đúng bao nhiêu lần" |

## 4. Hiểu biết về con người — **giả thuyết, chưa kiểm**

Rút từ hội đồng phản biện 2026-10-09 (tâm lý hành vi, JTBD, đầu tư, sản phẩm
AI, người dùng mô phỏng). **Không có điều nào ở đây đến từ người thật.** Mỗi
điều là một câu hỏi để mang đi hỏi, không phải một sự thật để xây lên.

1. **Người ta không cảm nhận được sự im lặng.** Con người học từ những gì xảy
   ra, gần như không học từ những gì không xảy ra. Một công cụ có giá trị nằm
   ở chỗ im lặng thì trông y như một công cụ đã chết.
2. **Việc bị bỏ dở phần lớn là việc người ta né, không phải việc người ta
   quên.** Nhắc một việc đang bị né sẽ bị dismiss, rồi người ta né luôn công
   cụ. Đòn bẩy có bằng chứng mạnh nhất nằm ở *lúc nhận việc* (biến việc mơ hồ
   thành "khi nào, bước đầu là gì"), không nằm ở lúc nhắc.
3. **Thông báo công khai về tiến độ là bêu tên bằng máy.** Chỉ người quản lý
   thích, những người còn lại sẽ mute. Muốn giữ thể diện thì phải báo riêng
   *trước*, để người trong cuộc tự quyết có công khai hay không.
4. **Thuật toán chỉ cần sai một lần là bị bỏ** (algorithm aversion). Số liệu
   sai mà đăng công khai một lần là người ta thôi tin mọi lần sau.
5. **Nhu cầu đau nhất có thể không nằm ở người được giao việc**, mà ở người
   chủ trì cuộc họp: muốn biết việc nào còn mở, của ai, trước buổi kế tiếp.
6. **Có người cần *bằng chứng* "việc này đã được giao cho tôi"** hơn là cần
   được nhắc.
7. **Trong công việc, người ta muốn công cụ dễ đoán và trong tầm kiểm soát**,
   không muốn được "hiểu".

## 5. Lỗi dữ liệu đang nằm trong code

Hướng mới dùng lại phần nào thì phải sửa những lỗi sau trước:

- `mezon_bot/src/roomWatch.js:253`: mọi action item từ họp đều bị gán
  `due_date = hôm nay T00:00Z`. Từ ngày hôm sau, mọi việc đều thành "quá hạn",
  và deadline suy ra từ đó là giả.
- `project.will_miss` tính tốc độ dự án bằng nút "Xong" trên Cortex. Team nào
  đóng việc ở Jira thì tốc độ tính ra bằng 0, và bot báo sai "dự án sắp trễ"
  vào channel.
- Sau **mỗi** cuộc họp, mọi người tham gia đều bị hỏi "thuộc dự án nào?". Việc
  chung (`generalItems`) bị nhân bản vào task của từng người.
- Muốn nhận gì từ bot thì phải vào web lấy mã rồi gõ `*link`. Người không link
  thì không nhận được gì.
- `LIVE_TOOLS` có 22 tool, và prompt hệ thống dài 4.877 từ.

## 6. Tài sản đang có (trung lập, không phải lời khuyên dùng lại)

- **Bot Mezon** chạy được: DM, card tương tác (Xong / Dời), lệnh, theo dõi
  phòng họp, nhận biên bản từ bot họp ngoài (`orchestrator_service`, tuỳ
  chọn).
- **Hạ tầng:** EC2 t3.small, 5 container (`db`, `redis`, `backend`,
  `mezon_bot`, Caddy), tự khởi động.
- **Lõi deterministic:** `StateEvaluator` (predicate, chống lặp),
  `attention_gate.py` (dedup, quiet hours, gộp, im khi bận), delivery
  dispatcher (DM/channel), `feedback_loop`.
- **Dữ liệu:** tasks, projects (neo vào Mezon channel), Google Calendar sync,
  sự kiện lặp, `availability.find_free_slots`.
- **Hạ tầng ghi:** `CommandRegistry` (quyền, audit, snapshot, hoàn tác).
- **Đã đóng băng nhưng còn nguyên:** `stt_service` (diarization ở mức từ),
  `ocr_service`, `workflow_service`, Notes/Yjs.
- **Việc dở đã stash:** `stash@{0}` trên `feat_recurring` (model packages +
  execution mode).

## 7. Câu hỏi chưa ai trả lời

Hướng nào cũng nên trả lời những câu này bằng người thật trước khi code:

- Bot họp có thật sự được dùng đều trong công ty không? Tháng trước có bao
  nhiêu biên bản?
- Bot họp gán đúng người nhận việc được bao nhiêu phần trăm?
- Mọi người đóng việc ở đâu: Jira, Mezon, hay không đóng ở đâu cả?
- Lần gần nhất ai đó quên một việc được giao trong họp, chuyện gì đã xảy ra
  sau đó?
- Lần gần nhất họ tắt một bot hoặc công cụ nhắc việc là khi nào, và vì sao?
