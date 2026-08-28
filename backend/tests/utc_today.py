"""Ngày "hôm nay" theo **cùng thước với production**.

`app.services.today._today()` — thứ mọi predicate, ranking và digest đọc —
trả về ngày theo **UTC**. `date.today()` trả về ngày theo giờ máy.

Ở UTC+7 hai cái lệch nhau đúng một ngày trong khung 00:00–07:00 giờ VN. Một
test dựng việc "đến hạn hôm nay" bằng `date.today()` trong khung đó thực ra
dựng việc đến hạn *ngày mai* theo UTC — và code production **đúng** khi
không thấy nó.

Triệu chứng đã gặp: cả nhóm test day.plan/day.review/risk đỏ vào ban đêm,
xanh lại vào ban ngày, không ai đụng một dòng code nào. Đó là loại lỗi tốn
nhiều thời gian nhất để tin, vì bản sửa "thành công" đầu tiên chỉ là chờ
tới sáng.
"""

from datetime import date, datetime, timezone


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def utc_now() -> datetime:
    """"Bây giờ" dạng **naive UTC** — đúng cách DB lưu `tasks.due_date`.

    `datetime.now()` trả về giờ máy nhưng *không mang tzinfo*, nên nó được
    ghi thẳng vào cột như thể là UTC. Ở UTC+7 điều đó đẩy mọi mốc thời gian
    lên trước 7 tiếng: một việc "quá hạn một ngày" dựng lúc 00:08 giờ VN
    thực ra vẫn đến hạn *hôm nay* theo UTC, và code production đúng khi gọi
    nó là "Hạn hôm nay" chứ không phải "Quá hạn".
    """
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
