import pytest

from cortex_leads.guard.optout import wants_to_stop


@pytest.mark.parametrize("text", [
    "Đừng nhắn tin cho mình nữa nhé", "dung gui tin nua", "Mình không muốn nhận tin quảng cáo", "ngừng liên hệ giúp em",
    "đừng làm phiền chị nữa", "Hủy nhận tin", "unsubscribe", "STOP", "stop!", "bỏ nhận thông báo đi",
])
def test_a_request_to_stop_is_seen(text):
    assert wants_to_stop(text)


@pytest.mark.parametrize("text", [
    "em không gửi được ảnh", "Khóa IELTS giá bao nhiêu?", "chị đừng gọi giờ trưa nhé", "stop at the school gate",
    "mình đang tìm lớp, chưa muốn đăng ký", "thôi để mình xem lại", "dừng lại ở bước nào vậy",
])
def test_ordinary_talk_is_not_an_opt_out(text):
    assert not wants_to_stop(text)


def test_stop_calling_for_good_versus_for_lunch():
    assert wants_to_stop("đừng gọi nữa nhé") and not wants_to_stop("đừng gọi giờ trưa nhé")
