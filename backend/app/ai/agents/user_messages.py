"""Những câu Cortex nói khi có sự cố — viết cho người dùng, không cho log.

Các câu này từng nằm rải rác tám chỗ trong `agent_service.py` và dùng thuật
ngữ nội bộ: "Mô hình không trả về nội dung nào", "Dịch vụ AI đang có lỗi cấu
hình". Đo được hậu quả trong một cuộc trò chuyện mô phỏng — người dùng mới
cài app, nói "mình đang rối quá, cái deadline sắp tới làm mình lo muốn xỉu
luôn", và câu đầu tiên họ nhận được là:

    Mô hình không trả về nội dung nào. Bạn thử gửi lại sau ít phút nhé.

"Mô hình" là từ của người làm hệ thống. Người dùng không có mô hình nào; họ
có một deadline và đang lo.

Ba nguyên tắc cho mọi câu ở đây:

* **Không thuật ngữ nội bộ** — không "mô hình", "dịch vụ AI", "API",
  "token", "context". Người dùng nói chuyện với Cortex, không với một
  pipeline.
* **Trung thực, không giả vờ ổn.** Nói rõ là chưa làm được. Che đi thì
  người dùng ngồi đợi một câu trả lời không bao giờ tới.
* **Nói họ làm gì tiếp.** Một câu xin lỗi không có bước kế tiếp thì bỏ
  người dùng đứng đó.

Giữ ở một chỗ để cả hai đường (streaming và không) nói cùng một câu — cùng
lý do mà `notification_format.py` tồn tại.
"""

# Model trả về rỗng: không có nội dung, không có tool call.
EMPTY_REPLY = (
    "Mình chưa trả lời được câu này. Bạn thử nói lại theo cách khác giúp "
    "mình nhé?"
)

# Cấu hình sai phía server — người dùng không làm gì được, nhưng họ nên biết
# đây không phải lỗi của họ.
MISCONFIGURED = (
    "Có gì đó chưa đúng ở phía mình nên mình chưa xử lý được. Nếu tình "
    "trạng này lặp lại, bạn báo giúp mình nhé."
)

# Chạm giới hạn tần suất.
RATE_LIMITED = (
    "Mình đang xử lý hơi nhiều việc cùng lúc nên chậm lại một chút. Bạn "
    "đợi khoảng một phút rồi nhắc lại giúp mình nhé?"
)

# Không kết nối được tới nơi xử lý.
UNREACHABLE = (
    "Mình đang không kết nối được để xử lý câu này. Bạn thử lại sau một "
    "chút nhé?"
)

# Lỗi không rơi vào nhóm nào ở trên.
UNEXPECTED = (
    "Mình gặp vấn đề khi xử lý câu này. Bạn thử lại giúp mình nhé?"
)

# Đã chạy quá nhiều bước mà chưa xong — cắt để không chạy vô hạn.
#
# Trước đây câu này bảo người dùng "chia nhỏ ra, nói cụ thể hơn" — tức đổ
# việc của hệ thống sang cho họ, và sai sự thật: câu hỏi không hề mơ hồ,
# chỉ là nó cần nhiều bước hơn ngân sách một lượt của agent. Người dùng
# không làm gì sai để phải sửa cách hỏi.
#
# Đây là lưới cuối, dùng khi cả lượt tổng hợp tiến độ (xem
# `CONTINUATION_INSTRUCTION` trong agent_service.py) cũng hỏng, nên không
# có gì cụ thể để nói đã xong tới đâu — nhưng vẫn phải mời tiếp tục, không
# phải mời đổi cách hỏi.
TOO_MANY_STEPS = (
    "Việc này cần nhiều bước hơn mình xử lý được trong một lượt. Bạn gõ "
    "\"tiếp tục\" để mình làm nốt nhé — mình sẽ tiếp tục đúng từ chỗ đang "
    "dang dở, không cần bạn nhắc lại yêu cầu."
)
