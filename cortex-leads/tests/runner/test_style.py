"""WP15: giọng văn. STYLE.md + ví dụ giọng thật vào ngữ cảnh, cụm 'giọng AI' bị validator chặn."""
import subprocess
import sys
from pathlib import Path

import pytest
from wp5_support import GOOD_DRAFT, gateway, reply, run_one, world  # noqa: F401

from cortex_leads.core.envelope import BlockedCode
from cortex_leads.guard.validator import validate_draft
from cortex_leads.runner import context_builder as cb
from cortex_leads.skills.loader import lint, parse_skill_md
from cortex_leads.skills.profile import load_profile
from tests.skills.test_skills import PACK, SKILLS

ROOT = Path(__file__).resolve().parents[2]
V3 = ["hoi-lai-khach-im", "hoi-lai-dung-hen"]
BANNED = ["Rất vui được hỗ trợ chị", "Dưới đây là thông tin khoá học", "Hy vọng thông tin trên hữu ích",
          "Kính gửi chị An", "Cảm ơn bạn đã liên hệ với chúng tôi", "Tôi hiểu rằng bạn đang phân vân",
          "Đừng ngần ngại nhắn em nhé", "Nếu bạn có bất kỳ câu hỏi nào", "Khoá này thật tuyệt vời",
          "Lịch học hoàn hảo cho chị", "Đây là giải pháp tối ưu", "Chúng tôi cam kết đầu ra",
          "Xin lưu ý rằng giá có thể đổi", "Quý khách vui lòng chờ",
          "Em luôn ở đây nếu chị cần", "Em luôn sẵn sàng hỗ trợ chị", "Em đồng hành cùng bé nhé"]
NATURAL = [
    "Dạ chị, lớp IELTS đầu tháng còn chỗ, chị muốn em giữ chỗ giúp không ạ?",
    "Dạ chị cứ xem thoải mái nha, có gì chị cần em giải thích thêm cứ nhắn em.",
    "Em hỏi lại chuyện bé lớp 12 của chị, chị còn muốn tìm lớp thi thử không ạ?",
    "Dạ anh, anh đang định niềng để chỉnh khớp cắn hay cho đẹp ạ?",
    "Dạ em hiểu chị thấy hơi cao, chị dự tính khoảng bao nhiêu để em xem giúp ạ?",
    "Dạ qua đầu tháng rồi, chị sắp xếp được lịch học chưa ạ?",
    "Em gửi chị phần tóm tắt để chị chuyển anh xem cho tiện nha.",
    "Dạ tuần này bên em có buổi học thử miễn phí, chị rảnh buổi nào ạ?",
    "Khi nào chị cần cứ nhắn em nha, em nhắn lại liền ạ.",
    "Dạ chắc chắn có lớp cuối tuần ạ, chị muốn em gửi lịch không?",
]


def _violations(text: str, never_say: list[str]):
    return validate_draft(text, [], [], never_say=never_say, touches=0, max_touches=3,
                          opted_out=False, has_new_info=True, now=cb_now())


def cb_now():
    from datetime import UTC, datetime
    return datetime(2026, 10, 12, 3, 0, tzinfo=UTC)


@pytest.mark.parametrize("name", V3)
def test_v3_skills_lint_clean_and_block_ai_voice(name):
    manifest, body = parse_skill_md(SKILLS / name / "SKILL.md")
    assert manifest.version >= 3 and manifest.field_count() <= 15
    assert lint(manifest, load_profile("customer_drafter@1"), PACK) == []
    assert body.count("**") // 2 >= 6 and "reason_code" in body and "Lần chạm cuối" in body
    for text in BANNED:
        assert [v.code for v in _violations(text, manifest.never_say)
                if v.code == BlockedCode.FORBIDDEN_PHRASE], text
    for text in NATURAL:
        assert _violations(text, manifest.never_say) == [], text


async def test_style_loaded_and_shape_still_last(world):  # noqa: F811
    gw, prov = gateway(reply({"act": "none"}))
    await run_one(world, gw)
    user = prov.calls[0]["messages"][1]["content"]
    style = (ROOT / "sandboxes/customer_care/STYLE.md").read_text(encoding="utf-8")
    assert style.strip()[:80] in user and "Rất vui được hỗ trợ" in user
    assert '"max_touches": 3' in user and '"touches": 0' in user
    assert user.rstrip().splitlines()[-1].startswith("Nếu không nên nhắn")


async def test_voice_examples_win_and_context_is_trimmed(world, tmp_path, monkeypatch):  # noqa: F811
    d = tmp_path / str(world.t.id)
    d.mkdir()
    (d / "customer_care.md").write_text("Dạ chị Hoa ơi, em VOICE_MARK nè\n" + "x " * 40000, encoding="utf-8")
    monkeypatch.setattr(cb, "VOICE_DIR", tmp_path)
    gw, prov = gateway(reply({"act": "none"}))
    await run_one(world, gw)
    user = prov.calls[0]["messages"][1]["content"]
    assert "VOICE_MARK" in user and "ưu tiên hơn ví dụ trong skill" in user
    assert len(user) <= load_profile("customer_drafter@1").token_budget * cb.CHARS_PER_TOKEN
    assert user.rstrip().splitlines()[-1].startswith("Nếu không nên nhắn")  # shape survives


def test_style_block_trims_and_tolerates_missing_files(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "VOICE_DIR", tmp_path)
    assert len(cb.style_block("customer_care", "t", 300)) == 300
    assert cb.style_block("customer_care", "t", -5) == ""
    assert cb.style_block("no_such_sandbox", "t", 999) == ""


def test_sample_voice_file_has_ten_examples():
    text = (ROOT / "sandboxes/customer_care/voice_examples.sample.md").read_text(encoding="utf-8")
    assert sum(1 for ln in text.splitlines() if ln[:3].strip(". ").isdigit()) == 10


def test_eval_script_runs_35_cases_on_fake(tmp_path):
    out = tmp_path / "r.md"
    r = subprocess.run([sys.executable, "-m", "dev.eval_skills", "--provider", "fake", "--out", str(out)],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    md = out.read_text(encoding="utf-8")
    assert md.count("\n### ") == 35 and "35/35" in md
