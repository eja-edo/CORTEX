"""
Attention Bundle Queue (Milestone 6.1 M3 — steps 4-5, bundling + timing).

Step 3 of the Gate (attention_gate.py) can downgrade a non-critical
candidate to SILENT while the user is busy. Before M3, that was the end of
the story — a silenced candidate was simply never delivered. This module is
where it goes instead: `enqueue_async`/`enqueue_sync` are called by the Gate
right after a busy-downgrade, and `AttentionBundleWorker` (attention_bundle_worker.py)
periodically finds users who've become free again and turns everything
they accumulated into one Notification — the planning doc's own scenario
for 6.1 ("8 candidates during a meeting -> 0 during, 1 bundled after").

Khoá gộp là **(người, dự án)**, không phải chỉ người (DESIGN 7.2). Ba việc
của ba dự án khác nhau là ba chuyện khác nhau, và trộn chúng vào một tin
buộc người đọc tự tách ra — đúng thứ P5 muốn tránh. Cùng lượng thông tin,
gom đúng chỗ, và mỗi tin có một nhãn nói ngay nó về đâu.

Gộp **theo** dự án không phải phát **vào** dự án: `BUNDLE_REASON_KEY` giữ
phạm vi `PERSONAL`, nên mọi cụm đều về DM (DESIGN 8.1). Xem chú thích ở
`_compose_bundle`.

Đường flush **không** đi qua `request_attention_async`, nên hai luật của
Gate phải được áp lại ở cửa ra — và khoảng chờ chính là khoảng thời gian
chúng tồn tại để canh: `_drop_superseded` (một reason mạnh hơn đã nói mất
về cùng item trong lúc chờ) và dedup ở `_release_scoped_row`.

Hệ quả của điều trên: **lời nhắc cấp dự án không được gộp.** Gộp đổi được
thời điểm, không được đổi người nhận — mà một cụm `PERSONAL` thì về DM,
còn `project.slipping` phải về channel của cả nhóm. `_split_by_scope` tách
chúng ra và `_release_scoped_row` phát lại từng cái nguyên `reason_key`
gốc, tức là nguyên đường định tuyến của nó.

The bundle Notification itself does **not** go back through the Gate. It
already *is* the Gate's output for those candidates — re-gating it would be
asking "is it worth mentioning that I decided this was worth mentioning",
and could in principle silence itself forever if the user is back-to-back
busy. `flush_due_bundles` only fires once `is_user_busy` is false, which is
the Gate's own step-3 predicate — so the timing rule ("khi nào tốt" — leaving
a busy state) is honoured, just from the flush side instead of the
candidate side.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import (
    AttentionBundleQueue,
    AttentionChannel,
    AttentionItemType,
    AttentionLevel,
    Project,
    Schedule,
    Task,
)
from app.repositories.attention_log import AttentionLogRepository
from app.schemas import AttentionSurfaceCreate
from app.services.attention_log import AttentionLogService
from app.services.attention_reason_catalog import (
    ReasonScope,
    base_level_for,
    scope_for,
    superseded_by,
)
from app.services.availability import is_user_busy
from app.services.notifications import create_notification_async
from app.utils.logger import get_logger

logger = get_logger(__name__)

BUNDLE_REASON_KEY = "attention.bundle"

# `Notification.title` là `String(255)`. Tiêu đề ở đây được ghép từ tiền tố
# cố định + tên dự án + tiêu đề của item, nên nó vượt ngưỡng được — và một
# lời nhắc bị mất vì `StringDataRightTruncation` là kiểu hỏng tệ nhất mà
# module này có thể gây ra: người dùng im lặng không nhận được gì.
_TITLE_LIMIT = 255


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fit(title: str) -> str:
    return title if len(title) <= _TITLE_LIMIT else title[: _TITLE_LIMIT - 1] + "…"


async def _resolve_project_id_async(
    session: AsyncSession, item_type: AttentionItemType, item_id: UUID
) -> UUID | None:
    """Dự án của item, đọc **lúc xếp hàng** — xem `AttentionBundleQueue`.

    `None` là kết quả hợp lệ và thường gặp, không phải lỗi tra cứu:

    - `USER` (`day.review`, `day.plan`) không nói về một item nào, nên
      không thuộc dự án nào.
    - `COMMITMENT` chưa có đường nối tới dự án.
    - Một `SCHEDULE` chưa được gắn dự án — theo DESIGN 4.2 thì đó là phần
      lớn sự kiện, và cố đoán ra dự án từ hình dạng lịch là điều P7 cấm.
    - Item đã bị xoá giữa lúc Gate quyết định im và lúc hàng này được ghi.

    `PROJECT` (`project.slipping`, `project.will_miss`) tự trỏ vào dự án:
    `item_id` **là** `projects.id`.
    """
    if item_type is AttentionItemType.PROJECT:
        return item_id
    if item_type is AttentionItemType.TASK:
        return await session.scalar(select(Task.project_id).where(Task.id == item_id))
    if item_type is AttentionItemType.SCHEDULE:
        row = (
            await session.execute(
                select(Schedule.project_id, Schedule.recurrence_id).where(Schedule.id == item_id)
            )
        ).first()
        if row is None:
            return None
        project_id, recurrence_id = row
        if project_id is not None or recurrence_id is None:
            return project_id
        # Occurrence của một chuỗi. `schedules.project_id` cố ý chỉ nằm
        # trên hàng template (DESIGN 3.2) — đặt lên từng lần lặp thì một
        # chuỗi 30 lần đẻ 30 hàng cùng dự án và quy tắc suy ra sẽ trôi.
        # Nên đọc phải đi ngược lên template, đúng chiều mà 4.2 mô tả:
        # học một lần từ một occurrence, áp cho cả chuỗi.
        return await session.scalar(
            select(Schedule.project_id).where(Schedule.id == recurrence_id)
        )
    return None


def _resolve_project_id_sync(
    session: Session, item_type: AttentionItemType, item_id: UUID
) -> UUID | None:
    """Bản sync của hàm trên — Gate có hai đường và cả hai đều xếp hàng."""
    if item_type is AttentionItemType.PROJECT:
        return item_id
    if item_type is AttentionItemType.TASK:
        return session.scalar(select(Task.project_id).where(Task.id == item_id))
    if item_type is AttentionItemType.SCHEDULE:
        row = session.execute(
            select(Schedule.project_id, Schedule.recurrence_id).where(Schedule.id == item_id)
        ).first()
        if row is None:
            return None
        project_id, recurrence_id = row
        if project_id is not None or recurrence_id is None:
            return project_id
        return session.scalar(select(Schedule.project_id).where(Schedule.id == recurrence_id))
    return None


async def enqueue_async(
    session: AsyncSession,
    *,
    user_id: UUID,
    item_type: AttentionItemType,
    item_id: UUID,
    reason_key: str,
    title: str,
    body: str | None,
    payload: dict[str, Any] | None,
    actions: list[dict[str, Any]] | None,
    attention_log_id: UUID | None,
) -> AttentionBundleQueue:
    entry = AttentionBundleQueue(
        user_id=user_id, item_type=item_type, item_id=item_id, reason_key=reason_key,
        project_id=await _resolve_project_id_async(session, item_type, item_id),
        title=title, body=body, payload=payload or {}, actions=actions or [],
        attention_log_id=attention_log_id,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


def enqueue_sync(
    session: Session,
    *,
    user_id: UUID,
    item_type: AttentionItemType,
    item_id: UUID,
    reason_key: str,
    title: str,
    body: str | None,
    payload: dict[str, Any] | None,
    actions: list[dict[str, Any]] | None,
    attention_log_id: UUID | None,
) -> AttentionBundleQueue:
    entry = AttentionBundleQueue(
        user_id=user_id, item_type=item_type, item_id=item_id, reason_key=reason_key,
        project_id=_resolve_project_id_sync(session, item_type, item_id),
        title=title, body=body, payload=payload or {}, actions=actions or [],
        attention_log_id=attention_log_id,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def _compose_bundle(
    rows: list[AttentionBundleQueue], project_name: str | None
) -> tuple[str, str, list[dict[str, Any]], dict[str, Any]]:
    """Returns `(title, body, content, payload)`.

    `project_name` là nhãn gộp (DESIGN 7.2). Dự án cá nhân cũng có tên và
    cũng dùng nhánh này — 7.2 nói rõ: *"việc thuộc dự án cá nhân gộp như
    hiện tại, nhưng nhãn gộp là tên dự án cá nhân, không phải một nhóm vô
    danh"*. `None` chỉ dành cho những hàng thật sự không thuộc dự án nào
    (`item_type='user'`, hay sự kiện chưa gắn dự án), và chúng giữ nguyên
    từng chữ của cách nói cũ.

    Tiền tố *"Trong lúc bạn bận"* ở lại trong cả hai nhánh, kể cả nhánh có
    tên dự án. Bỏ nó đi thì *"Alpha có 3 việc cần chú ý"* đọc y hệt một
    cảnh báo cấp dự án — tức là `project.slipping`, thứ đi về **channel
    chung** chứ không về DM. Hai câu trông giống nhau mà đi hai nơi khác
    nhau là cách chắc chắn để người dùng thôi tin vào việc Cortex chọn
    kênh.

    Both `body` (a single " • "-joined line) and `content` (one text block
    per item) carry the same list, deliberately redundant: `body` is what
    the compact single-line surfaces read (NotificationsPage's row
    snippet only looks at `body`, never `content`); `content`, rendered
    through BlockRenderer, is what the detail modal prefers and is what
    actually stacks one item per line — `_build_notification` only
    auto-derives `content` from `body` when `content` is omitted, and that
    auto-derived single block doesn't get the `white-space: pre-wrap` CSS
    a hand-built multi-line `body` would need, so passing embedded `\n`s in
    `body` alone silently collapsed to one line in the modal. Building the
    blocks explicitly here sidesteps that rather than special-casing the
    frontend for one notification type.
    """
    if project_name is None:
        if len(rows) == 1:
            title = f"Trong lúc bạn bận: {rows[0].title}"
        else:
            title = f"Trong lúc bạn bận có {len(rows)} việc cần chú ý"
    elif len(rows) == 1:
        title = f"Trong lúc bạn bận — {project_name}: {rows[0].title}"
    else:
        title = f"Trong lúc bạn bận — {project_name} có {len(rows)} việc cần chú ý"
    title = _fit(title)
    body = " • ".join(row.title for row in rows)
    content = [{"type": "text", "text": f"• {row.title}"} for row in rows]
    payload = {
        # Nhãn gộp, để bề mặt nào cần thì đọc thay vì phải tách lại từ
        # `title`. Cố ý **không** kèm `source_channel_id`: đó là khoá mà
        # `DeliveryPayload.project_channel_id` đọc để định tuyến, và một
        # cụm nhắc việc riêng của một người phải ở lại DM kể cả khi nó
        # được gom dưới tên dự án (DESIGN 8.1 — gộp *theo* dự án không
        # phải phát *vào* dự án).
        "project_id": str(rows[0].project_id) if rows[0].project_id else None,
        "project_name": project_name,
        "bundled_items": [
            {
                "item_type": row.item_type.value,
                "item_id": str(row.item_id),
                "reason_key": row.reason_key,
                "title": row.title,
                "payload": row.payload,
            }
            for row in rows
        ]
    }
    return title, body, content, payload


async def _users_with_pending_bundles(session: AsyncSession) -> list[UUID]:
    stmt = (
        select(AttentionBundleQueue.user_id)
        .where(AttentionBundleQueue.flushed_at.is_(None))
        .distinct()
    )
    return list((await session.execute(stmt)).scalars().all())


async def _pending_rows_for_user(session: AsyncSession, user_id: UUID) -> list[AttentionBundleQueue]:
    stmt = (
        select(AttentionBundleQueue)
        .where(AttentionBundleQueue.user_id == user_id, AttentionBundleQueue.flushed_at.is_(None))
        .order_by(AttentionBundleQueue.queued_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def _drop_superseded(
    session: AsyncSession, rows: list[AttentionBundleQueue], now: datetime
) -> list[AttentionBundleQueue]:
    """Bỏ những hàng đã bị một reason mạnh hơn nói mất trong lúc chờ.

    Đây là luật supersession của Gate (`SUPERSEDES`), áp lại ở cửa ra. Nó
    phải có ở đây vì đường flush **không** đi qua `request_attention_async`,
    và khoảng chờ chính là khoảng thời gian luật đó tồn tại để canh:

        10:00  đang họp · `task.overdue` bắn → RECOMMEND, không critical
               → im vì bận → vào hàng đợi
        10:30  vẫn họp  · `task.at_risk` bắn → ASK, nằm trong
               `_CRITICAL_LEVELS` → **không** bị im → nói ngay
        11:00  hết họp  · flush

    Không có hàm này, 11:00 người dùng nhận *"việc quá hạn"* sau khi đã
    nhận *"việc có nguy cơ trễ cao"* về **cùng một việc** — tin cũ, nhẹ
    hơn, đến sau tin mới, nặng hơn. Đúng thứ `SUPERSEDES` được viết ra để
    chặn, chỉ là đi vào bằng cửa sau.

    Hàng bị bỏ vẫn được đánh dấu `flushed_at`: nó đã được xử lý xong, kết
    luận là im, và không được phép quay lại ở lượt quét sau. Không ghi
    `attention_log` — Gate cũng không ghi gì khi nó chặn vì supersession.

    Hàng không có reason mạnh hơn (`superseded_by` trả rỗng, tức phần lớn)
    không tốn một truy vấn nào.
    """
    # Cục bộ, không phải ở đầu tệp: `attention_gate` đã import module này
    # (`enqueue_async`), nên import ngược ở mức module là vòng tròn. Dùng
    # chung hàm thay vì chép lại công thức cửa sổ — hai bản sao của cùng
    # một hằng số là hai bản sẽ trôi khỏi nhau.
    from app.services.attention_gate import _supersession_window_start

    repository = AttentionLogRepository(session)
    window_start = _supersession_window_start()
    kept: list[AttentionBundleQueue] = []

    for row in rows:
        stronger = superseded_by(row.reason_key)
        if not stronger:
            kept.append(row)
            continue
        already = await repository.find_last_spoken_any(
            user_id=row.user_id,
            item_id=row.item_id,
            reason_keys=stronger,
            since=window_start,
        )
        if already is None:
            kept.append(row)
            continue
        logger.info(
            "Bundle release superseded: %r for item %s already covered by %r",
            row.reason_key, row.item_id, already.reason_key,
        )
        row.flushed_at = now

    return kept


def _split_by_scope(
    rows: list[AttentionBundleQueue],
) -> tuple[list[AttentionBundleQueue], list[AttentionBundleQueue]]:
    """Tách `(hàng gộp được, hàng phải phát riêng)` theo phạm vi của reason.

    Gộp tồn tại để giảm số lần làm phiền **một người**. Một reason phạm vi
    `PROJECT` (`project.slipping`) không nói với một người — nó nói với cả
    nhóm, qua channel dự án (DESIGN 8.1). Trộn nó vào cụm cá nhân là đổi
    người nhận, không phải đổi thời điểm, và đó là thứ gộp không có quyền
    làm.

    Đây là một lỗi có thật, không phải phòng xa: `project.slipping` có mức
    nền `RECOMMEND`, không nằm trong `_CRITICAL_LEVELS` của Gate, nên nó
    **bị im khi bận** và đi qua đúng đường này. Trước khi có hàm này, cảnh
    báo *"Alpha đang chậm lại"* mà Gate giữ lại trong lúc họp sẽ ra dưới
    `reason_key='attention.bundle'` (phạm vi `PERSONAL`) và lặng lẽ về DM
    của một người thay vì channel của cả nhóm. `project.will_miss` thoát
    lỗi này chỉ vì mức nền của nó là `ASK` — tức là nhờ may, không nhờ
    thiết kế.
    """
    personal: list[AttentionBundleQueue] = []
    scoped: list[AttentionBundleQueue] = []
    for row in rows:
        if scope_for(row.reason_key) is ReasonScope.PROJECT:
            scoped.append(row)
        else:
            personal.append(row)
    return personal, scoped


async def _release_scoped_row(
    session: AsyncSession, row: AttentionBundleQueue, now: datetime
) -> bool:
    """Phát lại một hàng phạm vi dự án. Trả về *có nói ra hay không*.

    Giữ `reason_key` gốc là điểm mấu chốt: đó là thứ duy nhất
    `DeliveryPayload.project_channel_id` đọc để chọn channel. `payload`
    gốc đi kèm nguyên vẹn vì `source_channel_id` nằm trong đó.

    Supersession đã được lọc trước đó cho **mọi** hàng (`_drop_superseded`).
    Ở đây còn một luật nữa của Gate phải áp lại, vì phát lại là nói ra:
    **dedup** — cùng `(item, reason)` có thể đã được nói bằng một đường
    khác trong lúc chờ. Bị chặn thì dừng ở chỗ đánh dấu `flushed_at` mà
    không sinh notification: hàng đã xử lý xong, kết luận là im.

    `record_surface` ghi một hàng `attention_log` **mới**, không dùng lại
    `row.attention_log_id`. Hàng cũ ghi `level='silent'` — nó là biên bản
    của quyết định *không nói*, và treo một notification vào đó thì bảng
    tự mâu thuẫn: một quyết định im có tin nhắn, có cả phản hồi của người
    dùng. Lần nói này là một quyết định riêng, ở một mức riêng, tại một
    thời điểm riêng.

    Hai chỗ phải xấp xỉ, cả hai xấp xỉ về phía an toàn:

    - `type` suy từ `reason_key` (`project.slipping` → `project_slipping`).
      Bảng hàng đợi không lưu `type`; quy ước này đúng với mọi reason cấp
      dự án đang có, và chỉ nhánh này dùng tới nó.
    - Mức phát lấy mức **nền** của reason từ catalog. Mức thật lúc Gate
      quyết định là `SILENT` và không được lưu lại. Mức nền là xấp xỉ trung
      thực nhất — Gate đã kết luận "đáng nói, chỉ chưa phải lúc", nên phát
      lại đúng chỗ nó bắt đầu.

    `content` không có trong bảng hàng đợi; `_build_notification` tự dựng
    một khối từ `body`. Cụm cá nhân mất chi tiết này từ lâu rồi và đây
    không phải chỗ để sửa nó.
    """
    result = await AttentionLogService(session).record_surface(
        AttentionSurfaceCreate(
            item_type=row.item_type,
            item_id=row.item_id,
            reason_key=row.reason_key,
            level=base_level_for(row.reason_key),
            channel=AttentionChannel.IN_APP,
        ),
        user_id=row.user_id,
    )
    if result.suppressed or result.log is None:
        row.flushed_at = now
        return False

    notification = await create_notification_async(
        session,
        user_id=row.user_id,
        type=row.reason_key.replace(".", "_"),
        title=row.title,
        body=row.body or "",
        actions=list(row.actions or []),
        payload=dict(row.payload or {}),
        reason_key=row.reason_key,
        attention_level=base_level_for(row.reason_key),
        attention_log_id=result.log.id,
    )
    row.flushed_at = now
    row.bundle_notification_id = notification.id
    return True


def _group_by_project(
    rows: list[AttentionBundleQueue],
) -> dict[UUID | None, list[AttentionBundleQueue]]:
    """Khoá gộp thứ hai sau `user_id` (DESIGN 7.2).

    Giữ nguyên thứ tự `queued_at` của `rows`: dict Python giữ thứ tự chèn,
    nên nhóm nào có việc bị im sớm nhất thì được nhắc trước. Không sắp lại
    theo tên dự án hay theo số việc — thứ tự thời gian là thứ tự duy nhất
    ở đây có nghĩa với người đọc.
    """
    groups: dict[UUID | None, list[AttentionBundleQueue]] = {}
    for row in rows:
        groups.setdefault(row.project_id, []).append(row)
    return groups


async def _project_names(session: AsyncSession, ids: list[UUID]) -> dict[UUID, str]:
    """Tên đọc **lúc flush**, khác với `project_id` được chốt lúc xếp hàng.

    Chủ ý: dự án được đổi tên trong lúc người dùng đang họp thì lời nhắc
    nên gọi nó bằng tên hiện tại — người ta nhận ra dự án qua tên đang
    dùng, không qua tên hôm qua. Thứ phải bất biến là *item này thuộc dự
    án nào*, không phải *dự án đó tên gì*.

    Id không tra được (dự án đã xoá) vắng mặt trong dict và nhóm đó rơi về
    nhánh vô danh — vẫn được nhắc, chỉ mất nhãn.
    """
    if not ids:
        return {}
    rows = await session.execute(select(Project.id, Project.name).where(Project.id.in_(ids)))
    return {pid: name for pid, name in rows.all()}


async def flush_due_bundles(session: AsyncSession) -> int:
    """Flush every user whose pending bundle is ready to go out (no longer
    busy). Returns how many **notification** went out this sweep — một
    người có thể sinh ra nhiều, một cụm mỗi dự án (DESIGN 7.2) cộng với
    mỗi lời nhắc cấp dự án được phát riêng (xem `_split_by_scope`). The
    worker logs it, tests assert on it.

    One user at a time: a failure partway through (bad row, DB hiccup) must
    not roll back bundles for users who already succeeded in this same
    sweep, and the next sweep interval will simply retry whatever didn't
    get flushed.

    Bên trong một người thì commit **theo từng nhóm**, không dồn tới cuối.
    `create_notification_async` tự commit, nên nếu tiến trình chết giữa
    chừng, phần chưa đánh dấu `flushed_at` sẽ được nhắc lại ở lượt quét
    sau. Commit theo nhóm giữ cửa sổ đó đúng bằng một nhóm — dồn tới cuối
    thì một người có bốn dự án sẽ nhận lại cả bốn.
    """
    flushed = 0
    for user_id in await _users_with_pending_bundles(session):
        try:
            if await is_user_busy(session, user_id):
                continue
            rows = await _pending_rows_for_user(session, user_id)
            if not rows:
                continue

            rows = await _drop_superseded(session, rows, _naive_utcnow())
            if not rows:
                # Mọi hàng đều đã bị nói mất. `flushed_at` của chúng vừa
                # được đặt, phải commit trước khi đi tiếp — nếu không lượt
                # quét sau lại xử lý lại đúng những hàng đó.
                await session.commit()
                continue

            personal_rows, scoped_rows = _split_by_scope(rows)

            for row in scoped_rows:
                spoke = await _release_scoped_row(session, row, _naive_utcnow())
                # Commit kể cả khi im: `flushed_at` đã được đặt, và hàng
                # không được phép quay lại ở lượt quét sau.
                await session.commit()
                if spoke:
                    flushed += 1

            if not personal_rows:
                continue

            groups = _group_by_project(personal_rows)
            names = await _project_names(session, [pid for pid in groups if pid is not None])

            for project_id, group_rows in groups.items():
                title, body, content, payload = _compose_bundle(
                    group_rows, names.get(project_id) if project_id is not None else None
                )
                notification = await create_notification_async(
                    session, user_id=user_id, type="attention_bundle", title=title, body=body,
                    content=content, payload=payload, reason_key=BUNDLE_REASON_KEY,
                    attention_level=AttentionLevel.INFORM,
                )
                now = _naive_utcnow()
                for row in group_rows:
                    row.flushed_at = now
                    row.bundle_notification_id = notification.id
                await session.commit()
                flushed += 1
        except Exception:
            await session.rollback()
            logger.exception("Failed to flush attention bundle for user %s", user_id)
    return flushed
