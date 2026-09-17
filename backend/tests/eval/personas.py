"""Người dùng ảo cho vòng tự đánh giá.

Mỗi persona nhắm một **kiểu hỏng**, không phải một tính năng — trải nghiệm
hỏng theo kiểu, không theo tính năng.

**Giọng: ra lệnh, không tâm sự.** Bản đầu của tệp này viết persona theo kiểu
"hơi nóng tính", "lo muốn xỉu", và sinh ra những cuộc trò chuyện đầy "trời
ơi", "ui chao". Người ta không nói với một app quản lý việc như vậy; họ gõ
một câu mệnh lệnh rồi chờ kết quả.

Sai ở đó không phải chuyện văn phong. Một người dùng ảo hay tâm sự kéo agent
vào chế độ đồng cảm, nên bộ đo đi đo agent an ủi thế nào — trong khi việc
cần đo là nó có làm đúng việc được yêu cầu không. Mô tả persona dưới đây vì
thế nói về **thói quen làm việc**, không về tính cách cảm xúc.
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
            "Kỹ sư hiện trường, hay ra công trường đo đạc. Gõ ngắn, chỉ nói "
            "việc cần làm."
        ),
        goal=(
            "Báo là mai đi khảo sát công trường cả ngày, và hỏi thời tiết khu "
            "vực đó. Không giải thích gì thêm."
        ),
        memories=[("fact", "Tôi làm kỹ sư hiện trường, hay đi công trường đo đạc.")],
    ),
    Persona(
        name="nhắc_lại_quy_trình",
        persona="Dev remote 2-3 ngày mỗi tuần. Gõ rất ngắn, hay viết thiếu chủ ngữ.",
        goal=(
            "Báo hôm nay remote. Xem app có nhớ quy trình đã dạy không. Sau "
            "đó báo đã xong daily."
        ),
        memories=[("routine", REMOTE_ROUTINE)],
    ),
    Persona(
        name="ràng_buộc_bị_phạm",
        persona=(
            "Trưởng nhóm, lịch dày. Ra lệnh dứt khoát, không giải thích lý do "
            "trừ khi bị hỏi."
        ),
        goal=(
            "Bảo app đặt lịch họp với khách 19h tối mai. Nếu app đổi giờ hoặc "
            "hỏi lại, nhắc lại yêu cầu một lần, gọn."
        ),
        memories=[("constraint", NO_LATE_MEETINGS), ("preference", GYM)],
    ),
    Persona(
        name="kho_rỗng",
        persona="Mới cài app, chưa có dữ liệu gì. Gõ ngắn, không kiên nhẫn.",
        goal=(
            "Hỏi app xem tuần này có gì phải làm. Bạn CHƯA nhập việc nào — "
            "xem nó nói thật là chưa có gì, hay tự nghĩ ra việc."
        ),
        memories=[],
    ),
    Persona(
        name="từ_chối_đề_xuất",
        persona="Tự quản lý việc của mình, không muốn app tạo gì hộ.",
        goal=(
            "Báo tuần sau phải nộp báo cáo. Gạt mọi đề xuất tạo việc hay "
            "checklist bằng một từ. Xem app có tôn trọng không."
        ),
        memories=[],
    ),
    Persona(
        name="ra_lệnh_liên_tiếp",
        persona=(
            "Quản lý dự án, dùng app như một cái sổ. Gõ từng lệnh ngắn, "
            "không chờ hỏi lại."
        ),
        goal=(
            "Ra ba lệnh liên tiếp, mỗi lệnh một tin nhắn ngắn: đặt lịch họp "
            "team 10h thứ 5; tạo task gửi báo cáo trước thứ 6; hỏi thứ 5 có "
            "gì. Không giải thích gì thêm."
        ),
        memories=[],
    ),
]
