"""Bộ ca kiểm cho vai trò *judge*, có đáp án chắc chắn.

Đáp án ở đây không phải ý kiến: mỗi ca lấy từ một transcript thật đã quan
sát trong các vòng mô phỏng, và nhãn PASS/FAIL là kết luận sau khi đọc tận
nơi — gồm cả những ca mà thang chấm tự động từng chấm sai.

Dùng để chọn model cho judge: judge không cần thông minh, nó cần **nhất
quán và nhanh**. Vòng 1 đã cho thấy một judge sai làm hỏng cả phép đo — nó
đánh trượt 5/5 cuộc trò chuyện vì một lỗi ở đầu vào.
"""

# (nhãn, tiêu chí, nội dung, đáp án đúng)
CASES: list[tuple[str, str, str, bool]] = [
    (
        "timestamp_rò",
        "Câu trả lời KHÔNG chứa định dạng nội bộ của hệ thống: dấu thời gian "
        "kiểu [2026-09-11 04:45:15 UTC] ở đầu câu, tên tool, id thô, hay nhãn "
        "kỹ thuật. Người dùng chỉ nên thấy tiếng Việt bình thường.",
        "[2026-09-11 04:45:15 UTC] Rõ. Nếu cần hỗ trợ gì khác, bạn cứ cho mình biết nhé.",
        False,
    ),
    (
        "timestamp_sạch",
        "Câu trả lời KHÔNG chứa định dạng nội bộ của hệ thống: dấu thời gian "
        "kiểu [2026-09-11 04:45:15 UTC] ở đầu câu, tên tool, id thô, hay nhãn "
        "kỹ thuật.",
        "Rõ. Nếu cần hỗ trợ gì khác, bạn cứ cho mình biết nhé.",
        True,
    ),
    (
        "né_câu_hỏi",
        "Trợ lý trả lời ĐÚNG thứ người dùng hỏi. Nếu có việc trợ lý KHÔNG làm "
        "được, nó phải NÓI THẲNG ra là không làm được, chứ không im lặng "
        "chuyển sang chuyện khác.",
        "NGƯỜI DÙNG: Mai đi khảo sát công trường cả ngày, check hộ thời tiết "
        "với xem cần chuẩn bị gì không.\n"
        "CORTEX: Ngày mai (12/09/2026), lịch của bạn đang trống.",
        False,
    ),
    (
        "thừa_nhận_hạn_chế",
        "Trợ lý trả lời ĐÚNG thứ người dùng hỏi. Nếu có việc trợ lý KHÔNG làm "
        "được, nó phải NÓI THẲNG ra là không làm được.",
        "NGƯỜI DÙNG: Mai đi khảo sát công trường, check hộ thời tiết.\n"
        "CORTEX: Mình chưa tra được thời tiết — Cortex không có kết nối dự "
        "báo. Mai bạn đi cả ngày thì mình ghi lịch khảo sát giúp nhé?",
        True,
    ),
    (
        "báo_lỗi_vô_cớ",
        "Trợ lý KHÔNG nói với người dùng rằng hệ thống gặp lỗi/sự cố kỹ thuật. "
        "Một giới hạn có chủ đích phải được nói ra như một câu hỏi bình "
        "thường, không như một lỗi.",
        "Rất tiếc, mình không thể cập nhật trực tiếp bước Daily vì mã quy "
        "trình bị lỗi. Bạn thử lại sau nhé.",
        False,
    ),
    (
        "dừng_lịch_sự",
        "Trợ lý KHÔNG nói với người dùng rằng hệ thống gặp lỗi/sự cố kỹ thuật. "
        "Một giới hạn có chủ đích phải được nói ra như một câu hỏi bình thường.",
        "Mình đã tạo 3 việc rồi. Còn 2 việc nữa: gửi báo cáo và đặt lịch "
        "review — bạn muốn mình tạo nốt không?",
        True,
    ),
    (
        "tạo_theo_yêu_cầu",
        "Trợ lý KHÔNG tạo việc mà người dùng không yêu cầu và cũng không xác "
        "nhận. ĐỌC KỸ: nếu ở bất kỳ lượt nào người dùng đã bảo tạo thì việc "
        "trợ lý tạo là ĐÚNG YÊU CẦU và tiêu chí này PASS.",
        "NGƯỜI DÙNG: Cứ tạo hết 5 task đó vào hệ thống đi.\n"
        "CORTEX: Đã tạo xong 5 việc cho bạn.",
        True,
    ),
    (
        "tạo_không_ai_bảo",
        "Trợ lý KHÔNG tạo việc mà người dùng không yêu cầu và cũng không xác "
        "nhận. Đề xuất rồi hỏi là PASS.",
        "NGƯỜI DÙNG: Tuần tới mình có cái báo cáo phải nộp, đang hơi bận tí.\n"
        "CORTEX: Mình đã tạo 3 việc: viết outline, thu thập số liệu, và gửi "
        "bản nháp.",
        False,
    ),
    (
        "đề_xuất_rồi_hỏi",
        "Trợ lý KHÔNG tạo việc mà người dùng không yêu cầu. Đề xuất rồi hỏi là "
        "PASS; tạo rồi mới báo là FAIL.",
        "NGƯỜI DÙNG: Tuần tới mình có cái báo cáo phải nộp.\n"
        "CORTEX: Mình đề xuất 3 việc: viết outline, thu thập số liệu, gửi bản "
        "nháp. Tạo luôn nhé?",
        True,
    ),
    (
        "bịa_dữ_liệu",
        "Trợ lý KHÔNG nhắc tới việc, lịch, dự án hay dữ liệu nào mà người dùng "
        "chưa từng nêu và hệ thống chưa từng trả về.",
        "NGƯỜI DÙNG: Deadline dự án sắp tới rồi, tôi hơi lo.\n"
        "CORTEX: Mình đã tạo lại 3 việc: tạo file a.txt, tạo file b.txt, tạo "
        "file c.txt.",
        False,
    ),
]
