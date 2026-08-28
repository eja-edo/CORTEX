"""Hai con số của phép thử A/B — `docs/DESIGN.md` mục 12.3.

    python -m scripts.ab_test_numbers

Nghiệm thu của Tuần 2 (13.3) là **"có số."** — đây là chỗ đọc chúng.

    1. Tỷ lệ dismiss                    — thấp hơn là tốt hơn
    2. Tỷ lệ được làm trong 24h sau khi nhắc  — cao hơn là tốt hơn

Nhóm chia theo `user_preferences.gate_bypass`:

    A (bypass = true)   đến hạn → ping một lần
    B (bypass = false)  qua Gate đầy đủ

**Một script, không phải một dashboard**, và đó là chủ ý: DESIGN 14 từ chối
dashboard vì "không ai mở lần thứ hai". Hai con số này được đọc đúng vài
lần trong đời sản phẩm — ở cuối phép thử — rồi dẫn tới một quyết định ở
12.4. Thứ được đọc vài lần thì thuộc về một lệnh chạy tay.

Quy tắc quyết định ở 12.4, chép lại để người đọc số không phải mở tài liệu:

    B hơn A rõ rệt trên cả hai số  → có hào, đi tiếp
    B hơn A không đáng kể          → Gate không phải hào ở sân này; chuyển
                                     sang bán engine cho bài toán alert
                                     fatigue

> ⚠️ Số nhỏ thì đừng đọc như số lớn. 20–30 action item chia đôi nghĩa là
> mỗi nhóm khoảng 10–15 quan sát; chênh lệch vài phần trăm ở cỡ đó là
> nhiễu. Script in cả mẫu số để điều đó không bị quên.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.database_async import make_async_sessionmaker
from app.models import (
    AttentionItemType,
    AttentionLog,
    AttentionResponse,
    Task,
    TaskStatus,
    UserPreferences,
)


async def _bypass_users(db) -> set:
    rows = await db.execute(
        select(UserPreferences.user_id).where(UserPreferences.gate_bypass.is_(True))
    )
    return set(rows.scalars().all())


async def collect() -> dict:
    engine, session_maker = make_async_sessionmaker()
    try:
        return await _collect(session_maker)
    finally:
        # `dispose()` sau một `return` bên trong `async with` là code chết —
        # engine rò cho tới khi tiến trình thoát. Với một script chạy tay
        # thì vô hại, nhưng nó là loại nhầm lẫn được sao chép đi chỗ khác.
        await engine.dispose()


async def _collect(session_maker) -> dict:
    async with session_maker() as db:
        group_a_users = await _bypass_users(db)

        logs = list(
            (
                await db.scalars(
                    select(AttentionLog).where(
                        # Chỉ những lần **thực sự nói ra**. Hàng `silent` là
                        # quyết định không nói — nó không có cơ hội bị
                        # dismiss, nên tính vào mẫu số sẽ làm tỷ lệ dismiss
                        # của nhóm B thấp giả tạo.
                        AttentionLog.level != "silent",
                        AttentionLog.item_type == AttentionItemType.TASK,
                    )
                )
            ).all()
        )
        if not logs:
            return {"A": _empty(), "B": _empty()}

        task_ids = {log.item_id for log in logs}
        tasks = {
            t.id: t
            for t in (await db.scalars(select(Task).where(Task.id.in_(task_ids)))).all()
        }

        buckets = {"A": [], "B": []}
        for log in logs:
            buckets["A" if log.user_id in group_a_users else "B"].append(log)

        return {name: _score(rows, tasks) for name, rows in buckets.items()}


def _empty() -> dict:
    return {"surfaced": 0, "dismissed": 0, "acted_24h": 0}


def _score(logs: list, tasks: dict) -> dict:
    dismissed = sum(1 for l in logs if l.response == AttentionResponse.DISMISSED)

    acted = 0
    for log in logs:
        task = tasks.get(log.item_id)
        if task is None or task.status is not TaskStatus.DONE or task.completed_at is None:
            continue
        # "Được làm trong 24h **sau khi nhắc**". Việc hoàn thành *trước* lần
        # nhắc không phải công của lần nhắc đó — tính vào là tự cho điểm.
        delta = task.completed_at - log.surfaced_at
        if timedelta(0) <= delta <= timedelta(hours=24):
            acted += 1

    return {"surfaced": len(logs), "dismissed": dismissed, "acted_24h": acted}


def _pct(part: int, whole: int) -> str:
    if whole == 0:
        return "—"
    return f"{part / whole * 100:.0f}% ({part}/{whole})"


def main() -> None:
    results = asyncio.run(collect())
    a, b = results["A"], results["B"]

    print("\nPhép thử A/B — DESIGN 12.3\n")
    print(f"{'':28} {'A (ngây thơ)':>18} {'B (qua Gate)':>18}")
    print(f"{'Số lần đã nhắc':28} {a['surfaced']:>18} {b['surfaced']:>18}")
    print(
        f"{'Tỷ lệ dismiss (thấp hơn tốt)':28} "
        f"{_pct(a['dismissed'], a['surfaced']):>18} "
        f"{_pct(b['dismissed'], b['surfaced']):>18}"
    )
    print(
        f"{'Làm trong 24h (cao hơn tốt)':28} "
        f"{_pct(a['acted_24h'], a['surfaced']):>18} "
        f"{_pct(b['acted_24h'], b['surfaced']):>18}"
    )

    smallest = min(a["surfaced"], b["surfaced"])
    if smallest < 10:
        print(
            f"\n⚠️  Nhóm nhỏ nhất mới có {smallest} quan sát. Chưa đủ để đọc — "
            "12.2 cần 20–30 action item chia đôi, tối thiểu 2 tuần."
        )
    print()


if __name__ == "__main__":
    main()
