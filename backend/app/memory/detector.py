import re
from typing import List

from app.memory.models.schemas import DetectionResult


class MemoryCandidateDetector:
    """
    Rule-based detector. KHÔNG gọi LLM.
    Nếu pass -> dua vao extraction queue.
    Nếu khong pass -> skip extraction hoan toan.
    """

    PREFERENCE_PATTERNS = [
        r'\b(tôi|mình|tao)\s+(thích|prefer|dùng|sử dụng|hay dùng)\b',
        r'\b(tôi|mình)\s+(không thích|ghét|tránh|không dùng)\b',
        r'\bi\s+(prefer|like|use|hate|avoid|always|never)\b',
        r'\bmy\s+(preferred|favorite|go-to|usual)\b',
        r'\b(tôi|mình)\s+(thường|hay)\s+(làm|code|viết|dùng)\b',
        r'(,|\.)\s*(thích|prefer|dùng|use)\b',
        r'\bthích\s+dùng\b',
    ]

    TECH_PATTERNS = [
        r'\b(dùng|using|running|on|with)\s+(python|fastapi|django|redis|postgresql|docker|linux|fedora|ubuntu|macos|windows|vscode|neovim|pycharm)\b',
        r'\bstack\s+(của|hiện tại|tôi dùng)\b',
        r'\b(os|operating system|editor|ide|framework|language)\s+(của|mình|tôi)\b',
    ]

    GOAL_PATTERNS = [
        r'\b(đang|am)\s+(build\w*|develop\w*|l[aà]m|vi[ếe]t|t[ạa]o|x[aâ]y d[ựu]ng|thi[ếe]t k[ếe])\b',
        r'\b(project|dự án|app|application|system|hệ thống)\s+(của|tôi|mình|tên là)\b',
        r'\b(mục tiêu|goal|plan|kế hoạch)\s+(là|của tôi)\b',
        r'\b(muốn|want to|plan to|going to)\s+(build\w*|create\w*|develop\w*|launch\w*)\b',
    ]

    DEADLINE_PATTERNS = [
        r'\b(deadline|due|hạn|phải xong|cần hoàn thành)\b',
        r'\b(ngày|tháng|tuần)\s+(sau|tới|này)\b.*\b(phải|cần|muốn)\b',
        r'\b(by|before|trước)\s+\w+\s+\d{1,2}\b',
        r'\blaunch\s+(on|by|before)\b',
    ]

    RELATIONSHIP_PATTERNS = [
        r'\b(sếp|manager|boss|teammate|đồng nghiệp|colleague|client|khách hàng)\b',
        r'\b(team|nhóm|group)\s+(của|tôi|mình)\b',
        r'\b(report to|làm việc với|work with)\b',
    ]

    IDENTITY_PATTERNS = [
        r'\b(tôi|mình|i\'m|i am)\s+(là|a|an)\s+\w+(er|or|ist|dev|engineer|designer|manager)\b',
        r'\b(tôi|mình|i)\s+(làm|work)\s+(ở|at|for)\b',
        r'\b(kinh nghiệm|experience|năm kinh nghiệm|years? of experience)\b',
        r'\b(fullstack)\s+(developer|engineer|dev)\b',
    ]

    TRIVIAL_PATTERNS = [
        r'\b(hôm nay|today)\s+(trời|weather|nóng|lạnh|đẹp|xấu)\b',
        r'\b(vừa ăn|just ate|ăn gì|what.*eat)\b',
        r'\b(mệt|tired|chán|bored|buồn ngủ|sleepy)\b',
        r'\b(ok|okay|ừ|uh|hmm|à|ờ)\b',
        r'^.{0,20}$',
    ]

    ALL_SIGNAL_GROUPS = [
        ("preference", PREFERENCE_PATTERNS, "high"),
        ("tech_stack", TECH_PATTERNS, "high"),
        ("goal", GOAL_PATTERNS, "high"),
        ("deadline", DEADLINE_PATTERNS, "medium"),
        ("relationship", RELATIONSHIP_PATTERNS, "medium"),
        ("identity", IDENTITY_PATTERNS, "high"),
    ]

    def detect(self, message: str) -> DetectionResult:
        message_lower = message.lower().strip()

        for pattern in self.TRIVIAL_PATTERNS:
            if re.search(pattern, message_lower, re.IGNORECASE):
                return DetectionResult(
                    should_extract=False,
                    signals=[],
                    priority="none",
                )

        triggered_signals = []
        highest_priority = "low"
        priority_order = {"high": 3, "medium": 2, "low": 1}

        for group_name, patterns, priority in self.ALL_SIGNAL_GROUPS:
            for pattern in patterns:
                if re.search(pattern, message_lower, re.IGNORECASE):
                    triggered_signals.append(group_name)
                    if priority_order[priority] > priority_order[highest_priority]:
                        highest_priority = priority
                    break

        if not triggered_signals:
            return DetectionResult(
                should_extract=False,
                signals=[],
                priority="none",
            )

        return DetectionResult(
            should_extract=True,
            signals=list(set(triggered_signals)),
            priority=highest_priority,
        )
