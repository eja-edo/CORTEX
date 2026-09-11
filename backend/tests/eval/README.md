# Bộ eval sống

Tám use case chạy trên **LLM thật, DB thật, embedding thật**. Không mock gì.

```bash
pytest -m live_llm tests/eval -v -s
```

`pytest` thường **không** chạy chúng — `pytest.ini` có `addopts = -m "not
live_llm"`, và `conftest.py` ở đây tự gắn marker cho mọi test trong thư
mục, nên không ai có thể quên đánh dấu một cái rồi vô tình gọi API tính
tiền trong lần chạy CI bình thường.

## Vì sao không mock

Bộ này tồn tại để trả lời một câu hỏi: *chất lượng giữa các phiên có lệch
nhau không?* Một mock trả lời giống hệt nhau mọi lần, tức là nó luôn báo
phương sai bằng 0 — đúng cái đang cần đo. Với câu hỏi này, mock không phải
là phiên bản rẻ hơn của phép đo; nó là phép đo sai.

## Bậc thang

| Cấp | Kiểm điều gì |
|---|---|
| 1 | Kho rỗng — không bịa ra quy trình chưa từng được dạy |
| 2 | Recall một mảnh; không gọi tool thừa; không hỏi lại thứ đã biết |
| 3 | Trigger sai — `deadline dự án` không được kéo theo quy trình remote |
| 4 | Bốn bộ nhớ, chọn đúng mảnh liên quan |
| 5 | Cùng câu hỏi ba lần — phương sai hành vi |
| 6 | Hội thoại hoàn toàn mới vẫn biết người dùng là ai |

Cấp 3 là cái đắt nhất. Đo được: với bộ nhớ remote, truy vấn `deadline dự
án` đạt điểm tương đồng **0.5844**, xếp *trên* cả `remote` (0.5810). Hai
dải chồng nhau nên không ngưỡng số nào tách được chúng — quy trình remote
**sẽ** lọt vào ngữ cảnh của một câu nói về deadline, ở mọi lượt. Phép chặn
cuối cùng vì thế là ngữ nghĩa: model phải đọc vế *"khi tôi remote"* và tự
thấy nó không mô tả hoàn cảnh vừa nêu. Cấp 3 kiểm đúng phép chặn đó, nên
nó là test đầu tiên đỏ nếu khối chỉ dẫn trong `UnifiedContext.
_render_memories()` bị sửa hỏng.

## Cách chấm

Hai tầng, chọn theo bản chất của thứ đang kiểm:

* **Sự thật cứng** — "có gọi `create_task` không" nằm trong bảng
  `agent_messages`. Đọc thẳng DB (`harness._tool_calls_for`), không hỏi
  model. Thay một phép kiểm chắc chắn bằng một phép đoán là đi lùi.
* **Ngữ nghĩa** — "câu trả lời này có đề xuất quy trình remote không" thì
  model diễn đạt bằng vô số cách. Giao cho `judge()` (`temperature=0`, ép
  trả về đúng một từ).

Không chỗ nào assert chuỗi chính xác: nó đo cách hành văn chứ không đo
hành vi, và sẽ đỏ mỗi lần model đổi cách diễn đạt.

## Khi một test đỏ

Đỏ ở đây **không** đồng nghĩa với "code hỏng" — model là một thành phần
không tất định. Trước khi sửa code, chạy lại một lần: đỏ ổn định là hồi
quy, đỏ chập chờn là phương sai, và bản thân phương sai cũng là dữ liệu
(đó là cấp 5).

Mọi test đều `print()` cả `tool_calls` lẫn nguyên văn câu trả lời, nên
chạy với `-s` sẽ thấy model thật sự nói gì thay vì chỉ thấy assertion nào
trượt.

## Số đo cơ sở (2026-09-10, sau P0)

8/8 xanh, 4 phút 38 giây cho cả bộ, mỗi lượt 17–29 giây.

Cấp 5 (cùng câu hỏi ba lần): **3/3 nhớ đủ ba bước, 0/3 tự tạo việc.** Đây
là con số P0 tồn tại để kéo về — trước khi recall là mặc định, biến gây
lệch chính là "lượt này model có nhớ gọi tool không", và đó là một quyết
định model đưa ra không tất định.

Một khoản nợ còn lại, ghi ở đây làm mốc: **`extract_memory` vẫn bị gọi
thừa ở 4/10 lượt** (L1, L2-b, L2-c, L5 run 1) dù cả system prompt lẫn mô
tả tool đều nói rõ bộ nhớ đã có sẵn trong ngữ cảnh. Không lượt nào cho kết
quả sai vì chuyện đó — chỉ tốn thêm một vòng LLM và ~10k token mỗi lần.
Nghi phạm là độ dài prompt: `estimated_system_prompt_tokens` đo được 9.868
cho một lượt, và chỉ dẫn càng dài thì model càng chọn lọc thứ nó tuân
theo. Đó là việc của P2 (gọt `assistant_system.md` về một hiến pháp ngắn);
con số 4/10 ở đây là mốc để so sánh sau khi gọt.

## Kịch bản L3 và khoản nợ nó canh

L3 ("deadline dự án sắp tới rồi, tôi hơi lo") là chỗ một lỗi ghi-dữ-liệu
lộ ra, và nó lộ ra **muộn**: bộ eval xanh nhiều lần trước khi có ai để ý.

Hiện tượng: agent gọi `get_project_tasks`, nhận danh sách rỗng, rồi tạo
sáu task `"Create file a.txt with content 'a'"` bằng tiếng Anh. Không
chuỗi nào trong đó có trong prompt, trong DB, hay trong bất kỳ kết quả
tool nào — model gặp khoảng trống và lấp bằng một mẫu quen từ dữ liệu
huấn luyện. Đã xác nhận bằng A/B rằng nó không do thang can thiệp, và có
sẵn từ `d39fb91`.

Số đo, tính theo số lượt agent **không** bịa:

| Cấu hình | Kết quả |
|---|---|
| Không có câu dặn kèm kết quả rỗng | 0/6 |
| Có câu dặn (cuối payload) | 2/3 |
| Có câu dặn (đầu payload) | 3/4 |

Có câu dặn thì khác hẳn không có. Vị trí thì **không** kết luận được ở cỡ
mẫu này. Khoảng ~1/4 lượt còn lại vẫn bịa — đó là giới hạn của model, và
L3 là chỗ theo dõi nó. Nếu con số này xấu đi, câu dặn trong
`app/ai/tools/empty_result.py` hoặc quy tắc tương ứng trong
`assistant_system.md` là nơi nhìn đầu tiên.

**Bài học chung, áp cho mọi eval về sau:** với mỗi tool ghi dữ liệu, phải
có ít nhất một kịch bản kiểm **trạng thái trong DB** sau lượt nói, không
chỉ kiểm câu trả lời và tên tool được gọi. Bộ này từng xanh 5/5 trong khi
một lỗi ghi sai xảy ra ở mọi lượt, đúng vì thiếu điều đó.

## Rate limit của embedding API

Chạy nhiều lần eval liên tiếp sẽ làm cạn quota của
`gemini/gemini-embedding-2-preview` và gây `429 Resource exhausted`. Khi đó
các test **tất định** cần embedding cũng đỏ theo — đo được: ba test trong
`tests/integration/test_procedures.py` đỏ ngay sau một loạt eval, rồi xanh
lại sau ~2 phút mà không sửa một dòng nào.

Nên khi một test embedding đỏ ngay sau khi chạy eval, hãy nghi rate limit
trước khi nghi code: `grep -c 429` trong log trả lời ngay. Quota reset
trong vòng khoảng hai phút.

Cũng vì vậy: **không chạy `pytest tests/unit tests/integration` song song
với bộ eval.** Ngoài chuyện tranh quota, `tests/conftest.py` còn `FLUSHDB`
đúng Redis database mà eval đang dùng làm cache embedding, nên hai bên vừa
làm chậm vừa làm nhiễu nhau.
