"""Người dùng ảo cho vòng tự đánh giá.

Mỗi persona nhắm một kiểu hỏng khác nhau, không phải một tính năng khác
nhau — vì thứ cần đo là trải nghiệm, và trải nghiệm hỏng theo kiểu, không
theo tính năng.
"""

from tests.eval.simulator import Persona

REMOTE_ROUTINE = (
    "Khi tôi remote thì phải daily trước 9h sáng, check-in trên web, "
    "và sync với team lúc 4h chiều."
)
NO_LATE_MEETINGS = "Tôi không bao giờ họp sau 18h vì phải đón con."
GYM = "Tôi luôn tập gym lúc 19:00 các ngày trong tuần."

PERSONAS: list[Persona] = [
    Persona(
        name="ngoài_trời",
        persona=(
            "Bạn là kỹ sư hiện trường, hay phải ra công trường đo đạc. Bạn "
            "thực dụng, không thích nói nhiều."
        ),
        goal=(
            "Cho Cortex biết mai bạn đi khảo sát công trường cả ngày, và xem "
            "nó có giúp bạn chuẩn bị gì không. Bạn quan tâm thời tiết và đồ "
            "cần mang."
        ),
        memories=[("fact", "Tôi làm kỹ sư hiện trường, hay đi công trường đo đạc.")],
    ),
    Persona(
        name="nhắc_lại_quy_trình",
        persona="Bạn là dev làm remote 2-3 ngày mỗi tuần. Bạn nói ngắn.",
        goal=(
            "Nói với Cortex là hôm nay bạn remote, xem nó có nhớ quy trình "
            "bạn từng dạy không. Sau đó báo là bạn đã làm xong daily."
        ),
        memories=[("routine", REMOTE_ROUTINE)],
    ),
    Persona(
        name="ràng_buộc_bị_phạm",
        persona=(
            "Bạn là trưởng nhóm, có con nhỏ nên phải về đúng giờ. Bạn hơi "
            "nóng tính khi phải nhắc lại điều đã nói."
        ),
        goal=(
            "Nhờ Cortex đặt lịch họp với khách vào 19h tối mai. Xem nó có "
            "nhớ ràng buộc của bạn không."
        ),
        memories=[("constraint", NO_LATE_MEETINGS), ("preference", GYM)],
    ),
    Persona(
        name="kho_rỗng",
        persona="Bạn mới dùng Cortex, chưa có dữ liệu gì trong đó.",
        goal=(
            "Bạn đang lo về một deadline sắp tới và muốn Cortex giúp. Bạn "
            "CHƯA nói cụ thể việc gì phải làm — xem nó hỏi bạn hay tự nghĩ ra."
        ),
        memories=[],
    ),
    Persona(
        name="từ_chối_đề_xuất",
        persona=(
            "Bạn thích tự quản lý việc của mình, không muốn app tạo việc hộ. "
            "Bạn từ chối dứt khoát."
        ),
        goal=(
            "Kể cho Cortex là tuần sau bạn phải nộp báo cáo. Nếu nó đề xuất "
            "tạo việc hay checklist, từ chối hết. Xem nó có tôn trọng không "
            "hay vẫn tạo."
        ),
        memories=[],
    ),
]
