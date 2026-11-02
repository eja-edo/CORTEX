import pytest

from cortex_leads.auth.passwords import strength_errors


@pytest.mark.parametrize("pw", ["Qwerty123456", "qwerty123456!", "Password2024!", "Matkhau2024"])
def test_a_common_word_dressed_up_with_digits_is_refused(pw):
    assert "Mật khẩu này quá dễ đoán." in strength_errors(pw)


def test_a_random_looking_password_is_accepted():
    assert strength_errors("tr0ng-Lop-hoc-Sao-Mai") == []
