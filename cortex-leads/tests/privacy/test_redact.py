import pytest

from cortex_leads.privacy.redact import redact


def test_phones_and_email_are_masked():
    r = redact("Gọi 0901 234 567 hoặc +84.912.345.678, mail a.b@x.vn, lại 0901234567")
    assert "0901" not in r.text and "+84" not in r.text and "@" not in r.text
    assert r.text.count("[PHONE_1]") == 2 and "[PHONE_2]" in r.text and "[EMAIL_1]" in r.text
    assert r.mapping["[EMAIL_1]"] == "a.b@x.vn"


NAME = ["Nguyễn Văn An"]




def test_full_name_given_name_and_honorific_forms_are_masked():
    for t in ["chị An", "a An", "An ơi", "nguyen van an", "NGUYỄN VĂN AN", "anh AN nhé", "chi an"]:
        out = redact(f"chào {t}", NAME).text
        assert out.startswith("chào [NAME_") and "An" not in out and "an" not in out.lower().replace("name", ""), out


def test_name_masked_with_or_without_diacritics_both_ways():
    r = redact("Nguyen Van An và Nguyễn Văn An", ["Nguyễn Văn An"])
    assert "Nguy" not in r.text
    assert redact("Bình ơi", ["Bình"]).text.startswith("[NAME_")
    assert redact("binh ơi", ["Bình"]).text.startswith("[NAME_")


def test_short_tokens_and_honorific_names_not_masked():
    assert redact("a e c", ["Lê E"]).text == "a e c"  # token < 2 chars / honorific
    assert redact("anh ơi", ["Nguyễn Anh"]).text == "anh ơi"  # given name equals an honorific
    assert "[NAME" in redact("Nguyễn Anh nhé", ["Nguyễn Anh"]).text  # full name still masked


def test_known_false_positive_common_word():
    # Documented trade-off: a given name that is also a word masks that word too.
    assert redact("rất an toàn", NAME).text == "rất [NAME_1] toàn"
    # whole-word only: "Anna" is untouched
    assert redact("Anna đến", NAME).text == "Anna đến"


def test_prices_are_not_phones():
    assert redact("Giá 2.500.000đ, 1.000.000.000").text == "Giá 2.500.000đ, 1.000.000.000"


@pytest.mark.parametrize("text,leak", [
    ("Em là Hà, tư vấn em khoá IELTS với", "Hà"),
    ("mình tên Nguyễn Thu Hà nha", "Nguyễn"),
    ("Tôi là anh Minh", "Minh"),
    ("Em là Hà. Hà muốn hỏi giá", "Hà"),
])
def test_self_introduced_name_is_masked(text, leak) -> None:  # R51: seen with a real model ("chị Hà")
    assert leak not in redact(text, ["Tên Facebook"]).text


@pytest.mark.parametrize("text", ["em là học sinh lớp 9", "chị là người nhà của bé"])
def test_self_introduction_without_a_name_is_left_alone(text) -> None:
    assert redact(text).text == text
