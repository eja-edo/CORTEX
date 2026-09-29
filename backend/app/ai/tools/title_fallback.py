"""Cứu `title` khi model nhét đúng nội dung vào sai trường.

Đo được trong một cuộc trò chuyện mô phỏng — hậu quả nặng nhất tìm ra trong
cả đợt tự đánh giá: model gọi `create_schedule` ba lần liên tiếp, luôn điền
đúng nội dung vào `description` ("Họp team") và để trống `title` (trường bắt
buộc). Cả ba lần đều bị validation từ chối với thông báo rõ ràng
`"loc":["title"],"msg":"Field required"`. Sau ba lần thất bại, thay vì thừa
nhận, agent **báo thành công**: "Mình đã ghi nhận lịch họp team vào 10:00
sáng Thứ 5" — trong khi bảng `schedules` của người dùng đó **rỗng hoàn
toàn**. Đây là vi phạm trực tiếp "Do not fabricate ... tool results", và nó
xảy ra vì cascade lỗi bắt đầu từ đúng một chỗ: `title` bị bỏ trống.

Cùng mẫu lặp lại với `create_task` trong cùng đợt đo: 9 lời gọi liên tiếp,
cùng lỗi, trước khi người dùng phải tự đánh vần "Tiêu đề: Gửi báo cáo" thì
mới qua.

Sửa ở prompt đã được thử và không đủ: mô tả trường `title` đã rõ ("What
needs doing, in the user's own words"), đứng đầu danh sách property, và
thông báo lỗi đã nêu đúng tên trường thiếu — model vẫn lặp lại sai lầm y
hệt nhiều lần. Nên sửa ở đây, tại biên tool: khi `title` trống mà
`description` có nội dung, model gần như chắc chắn đã định đưa đúng nội
dung đó làm tiêu đề, chỉ đặt sai trường. Dùng lại chính nội dung model đã
cung cấp — đây không phải bịa thêm, mà là định tuyến đúng chỗ.
"""


def rescue_title(
    data: dict, fallback_field: str = "description", clear_fallback: bool = True
) -> dict:
    """`model_validator(mode="before")`: nếu thiếu `title` mà có nội dung ở
    `fallback_field`, dùng nội dung đó làm `title`.

    Tổng quát hoá từ bản gốc (chỉ nhận `description`) để dùng lại được cho
    `save_procedure`: cùng đúng kiểu hỏng đo được ở đây lại xảy ra ở đó —
    model bỏ trống `title` của bước, chỉ điền `detail`, 100% số lần gọi
    trong lần eval sống đầu tiên (`tests/eval/test_save_procedure_live.py`,
    2026-09-22). Cùng kết luận của docstring module này vẫn đúng: sửa bằng
    câu chữ trong prompt đã không đủ ở ca gốc, nên không thử lại ở đây —
    vá tại biên tool ngay từ đầu.

    `clear_fallback=False` cho ca `fallback_field` vẫn cần giữ nguyên sau
    khi được mượn làm `title` — ví dụ `trigger_text` của `save_procedure`
    vẫn là trường bắt buộc riêng, không "trở thành tiêu đề" theo nghĩa
    `description`/`detail` (thứ chỉ tồn tại để bổ sung cho `title`).

    Cắt về tối đa 255 ký tự — `fallback_field` (`description`, 1000 ký
    tự; `detail`, 500 ký tự) có thể dài hơn giới hạn của `title`, và không
    cắt thì việc cứu trường này lại tạo ra chính lỗi validation nó định
    tránh.

    Không đụng gì khi `title` đã có — đây là lưới an toàn, không phải một
    cách viết `title` khác.
    """
    if not isinstance(data, dict):
        return data
    title = (data.get("title") or "").strip() if isinstance(data.get("title"), str) else data.get("title")
    if title:
        return data
    fallback = data.get(fallback_field)
    if isinstance(fallback, str) and fallback.strip():
        data = dict(data)
        data["title"] = fallback.strip()[:255]
        if clear_fallback:
            data[fallback_field] = None
    return data
