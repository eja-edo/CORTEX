"""Câu dặn đi kèm một kết quả rỗng.

Một danh sách rỗng là chỗ model hay bịa nhất, và nó không được phép im
lặng. Đo được (2026-09-10, kịch bản eval L3, tái hiện 6/6 lần): người dùng
nói "deadline dự án sắp tới rồi, tôi hơi lo", agent gọi
`get_project_tasks`, nhận `tasks: []`, rồi tạo sáu task "Create file a.txt
with content 'a'" bằng tiếng Anh — không chuỗi nào trong đó tồn tại ở
prompt, ở DB, hay ở bất kỳ kết quả tool nào. Model gặp khoảng trống và lấp
bằng một mẫu quen thuộc từ dữ liệu huấn luyện.

System prompt đã dặn "If a tool returns empty results: accept the result,
do not retry automatically" — và bị bỏ qua. Lời dặn đó nằm cách chỗ quyết
định hàng nghìn token; câu dặn đặt **ngay trong kết quả** thì model đọc nó
đúng lúc đang quyết định.

Dùng ở mọi tool đọc có thể trả về rỗng, để câu chữ nhất quán và để lần sau
sửa chỉ phải sửa một chỗ.
"""

# Giữ ngắn: nó đi kèm *mọi* kết quả rỗng, nên mỗi từ thừa là token nhân lên
# theo số lời gọi.
_TEMPLATE = (
    "{what} — đây là sự thật, không phải khoảng trống cần lấp. "
    "Nói với người dùng là chưa có gì, hoặc hỏi họ; tuyệt đối không tự "
    "nghĩ ra nội dung để điền vào."
)


def empty_note(what: str) -> str:
    """Câu dặn cho một kết quả rỗng. `what` mô tả cái gì rỗng."""
    return _TEMPLATE.format(what=what)


def with_empty_note(result: dict, is_empty: bool, what: str) -> dict:
    """Gắn `note` vào `result` khi nó rỗng, ngược lại trả nguyên vẹn.

    Note đứng **đầu** dict vì kết quả tool được serialize theo thứ tự
    chèn, nên model gặp câu dặn trước khi gặp danh sách rỗng. Đó là lý lẽ,
    không phải kết quả đo — xem dưới.

    Đo trên kịch bản eval L3, tính theo số lượt agent **không** bịa ra nội
    dung để lấp chỗ trống:

        không có note        0/6
        note ở cuối dict     2/3
        note ở đầu dict      3/4

    Kết luận rút ra được: **có note thì khác hẳn không note** (0/6 so với
    5/7 gộp lại). Kết luận KHÔNG rút ra được: vị trí có ích. 2/3 so với 3/4
    là chênh lệch không tách nổi khỏi nhiễu ở cỡ mẫu này — giữ note ở đầu
    vì lý lẽ đọc-tuần-tự, không vì đã chứng minh được.

    Khoản còn lại (~1/4 lượt vẫn bịa) là giới hạn của model, không phải
    thứ một câu dặn nữa sẽ đóng nốt. Ba tầng chặn cứng đã cân nhắc và loại:
    trích dẫn nguyên văn (model trích được *bất kỳ* câu thật nào của người
    dùng để biện minh cho một task bịa — nó kiểm câu *có tồn tại*, không
    kiểm câu *có liên quan*); giới hạn số lượng (ca đo được chỉ tạo 3 task
    thành công, dưới mọi ngưỡng hợp lý); và hạ trạng thái về
    `pending_confirm` (cũng cần phân biệt "người dùng đã nhờ" với "agent tự
    nghĩ", thứ code không biết). `tests/eval/` là chỗ canh khoản nợ này.
    """
    if is_empty:
        return {"note": empty_note(what), **result}
    return result
