"""The kinds of sandbox there are (WP32): one place that says, for a purpose, what it is called, which profile and folder
of skills it comes with, and which cron jobs it runs. A new kind is one entry here plus its `sandboxes/<dir>/` folder; before
this each of those facts lived in its own table (cron, CLI, console, skills) and a new sandbox meant editing all of them.
Pure data: the jobs are looked up only when asked for, so nothing here imports the code that uses it."""
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Jobs = Callable[[], list[tuple[Callable[..., Any], Callable[..., Any]]]]  # [(slot_of(now, tz), job(session, sandbox, tz, now, slot))]


def _no_jobs() -> list:
    return []


def _customer_care_jobs() -> list:
    from cortex_leads.cron.jobs import morning_list
    from cortex_leads.cron.schedule import morning_slot

    return [(morning_slot, morning_list)]


def _owner_digest_jobs() -> list:
    from cortex_leads.cron.jobs import monthly_digest, scan_signals, weekly_digest
    from cortex_leads.cron.schedule import monthly_slot, morning_slot, weekly_slot

    return [(morning_slot, scan_signals), (weekly_slot, weekly_digest), (monthly_slot, monthly_digest)]


@dataclass(frozen=True)
class SandboxKind:
    purpose: str                   # the slug stored in sandbox.purpose
    label: str                     # what the owner calls it
    about: str                     # one line under it in the sandbox list
    profile: str                   # profile_ref a new sandbox of this kind gets ("" = none yet)
    directory: str                 # sandboxes/<directory>/: skills, domain pack, style
    description: str = ""          # the card in the "new sandbox" panel
    jobs: Jobs = field(default=_no_jobs)
    customer_facing: bool = False  # talks to customers: has channels, a catalogue and a send mode (the page shows them)
    skills_off: tuple[str, ...] = ()  # shipped with the folder but not switched on at creation (e.g. a skill that is only for trying things)
    listed: bool = True            # offered as a card in the console
    available: bool = True         # ...and can be picked (false = shown greyed with `reason`)
    reason: str = ""


KINDS: dict[str, SandboxKind] = {k.purpose: k for k in (
    SandboxKind(
        "customer_care", "Chăm sóc khách", "Nói chuyện với khách tiềm năng, luôn qua nhân viên hoặc bộ kiểm",
        "customer_drafter@1", "customer_care", "Tư vấn, nhắc khách im, giữ chỗ học thử. Có thể thêm kênh và kỹ năng.",
        jobs=_customer_care_jobs, customer_facing=True, skills_off=("thu-nhanh",)),  # thu-nhanh says itself: "CHỈ ĐỂ THỬ, không bật trong sandbox thật"
    SandboxKind(
        "owner_digest", "Báo cáo cho chủ", "Số liệu tuần và đề xuất của AI tổng, không nhắn khách",
        "digest_template@1", "owner_digest", "Báo cáo tuần, đề xuất của AI tổng. Không bao giờ nhắn khách.",
        jobs=_owner_digest_jobs),
    SandboxKind(  # made from the command line: it needs a folder of recordings connected, which the console cannot do yet
        "lesson_recap", "Tổng kết buổi học", "Bản ghi buổi học thành tổng kết và bài tập về nhà cho đội, không nhắn khách",
        "lesson_recapper@1", "lesson_recap", listed=False),
    SandboxKind(  # made from the command line: it needs a Classroom course connected and a grading guide per assignment
        "classroom_grader", "Chấm bài Classroom", "Chấm bài nộp theo thang điểm của giáo viên và soạn bài tập; giáo viên duyệt mọi điểm",
        "classroom_grader@1", "classroom_grader", listed=False),
    SandboxKind(
        "student_care", "Hỗ trợ học viên", "", "", "student_care",
        "Trả lời lịch học, học phí, kết quả cho học viên và phụ huynh. Chỉ đọc dữ liệu.",
        available=False, reason="Chưa mở: chờ trung tâm xác nhận nhu cầu"),
)}


def kind_of(purpose: str) -> SandboxKind | None:
    return KINDS.get(purpose)
