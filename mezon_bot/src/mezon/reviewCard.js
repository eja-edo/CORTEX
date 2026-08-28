"use strict";

/**
 * Thẻ tổng kết cuối ngày (`day.review`) — một bản kiểm, không phải một danh sách.
 *
 * Bản trước liệt kê việc còn mở và dừng ở đó, nên nó trả lời *"còn gì"* mà
 * không trả lời *"hôm nay đi được bao xa"* — và cuối ngày thì câu thứ hai
 * mới là câu người ta hỏi. Một tỷ lệ đặt trước danh sách biến cùng dữ liệu
 * đó thành một kết luận: `3/8` đọc xong trong một nhịp, `còn 5 việc` thì
 * không, vì nó giấu mất mẫu số.
 *
 * **Việc đã xong hiện dạng đã tick, việc chưa xong hiện dạng ô trống, và
 * chỉ ô trống mới bấm được.** Ràng buộc thật của nền tảng: radio của Mezon
 * không có trạng thái "chọn sẵn" (`addRadioField` nhận options, description
 * và max, hết — xem `FormBuilder.radio` và ghi chú trong `modelCard.js`).
 * Nên tick sẵn là bất khả thi, và giả vờ có nó bằng cách đưa việc đã xong
 * vào nhóm chọn sẽ tệ hơn nhiều: người dùng bỏ tick một việc đã xong rồi
 * bấm Xác nhận sẽ *tưởng* mình vừa mở lại nó, trong khi không có gì xảy ra.
 * Trạng thái đã xong vì thế nằm ở phần chữ, nơi nó nói đúng sự thật.
 *
 * Nút Xác nhận không cần `pendingForms`: id các việc được tick quay về ngay
 * trong `values`, nên thẻ này hoạt động sau khi bot restart và sau khi TTL
 * của form hết — đúng yêu cầu của một DM nằm trong danh sách chat qua đêm.
 */

const { FormBuilder, STYLE, notice } = require("./embed");
const { actionId } = require("./actions");

const OPEN_FIELD_ID = "done_today";

/** Trần số dòng mỗi nhóm. Một tổng kết dài hơn thế không còn là tổng kết. */
const MAX_LISTED = 10;

/**
 * **Không dùng markdown trong `description` của embed.**
 *
 * Mezon không chỉ bỏ qua `**đậm**` — nó nuốt luôn *nội dung* bên trong.
 * Thẻ đầu tiên gửi đi in ra `việc — 17%` vì `**2/12**` biến mất sạch, và
 * hai tiêu đề nhóm cũng bốc hơi để lại hai dòng trống. Cấu trúc ở đây vì
 * thế phải làm bằng emoji, xuống dòng và chữ thường — thứ client hiển thị
 * đúng như đã gửi.
 */
function ratioLine(doneCount, totalCount) {
  if (totalCount === 0) return "Hôm nay không có việc nào đến hạn.";
  const pct = Math.round((doneCount / totalCount) * 100);
  return `Xong ${doneCount}/${totalCount} việc hôm nay — ${pct}%`;
}

/** "26/08" — đủ để phân biệt hai việc trùng tên, không hơn. */
function shortDue(value) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/**
 * @param payload  `DayReviewPayload` như backend gửi xuống.
 * @param notificationId  Dùng làm đích của nút, để log nối được về thông báo.
 */
function renderDayReview({ title, payload, notificationId }) {
  const done = Array.isArray(payload?.completed_today) ? payload.completed_today : [];
  const open = Array.isArray(payload?.still_open) ? payload.still_open : [];
  const doneCount = Number(payload?.completed_today_count ?? done.length) || 0;
  const openCount = Number(payload?.open_task_count ?? open.length) || 0;
  const overdue = Number(payload?.overdue_task_count ?? 0) || 0;

  const form = new FormBuilder(`🌙 ${title || "Tổng kết cuối ngày"}`);

  // Tỷ lệ đứng đầu và đứng một mình: cuối ngày câu người ta hỏi là "đi
  // được bao xa", và một con số phải đọc xong trong một nhịp.
  const blocks = [ratioLine(doneCount, doneCount + openCount)];
  if (overdue > 0) blocks.push(`⚠️ ${overdue} việc đã quá hạn`);

  // Chỉ liệt kê việc **đã xong**. Việc chưa xong nằm ngay dưới dạng ô tick
  // — in thêm một lần ở đây là bắt người đọc lướt qua cùng danh sách hai
  // lần rồi tự đối chiếu xem hai bản có khớp nhau không.
  if (done.length) {
    const shown = done.slice(0, MAX_LISTED);
    const lines = shown.map((item) => `✅ ${item.title}`);
    if (done.length > shown.length) {
      lines.push(`… và ${done.length - shown.length} việc nữa`);
    }
    blocks.push(lines.join("\n"));
  }
  form.description(blocks.join("\n\n"));

  const selectable = open.slice(0, MAX_LISTED).filter((item) => item.task_id);
  if (selectable.length) {
    form.radio(
      OPEN_FIELD_ID,
      "Chưa xong — tick việc bạn đã làm",
      selectable.map((item) => {
        // Hạn đi kèm nhãn vì nhiều việc trùng tên chỉ khác ngày ("10 từ
        // mới…" ×5). Không có nó, năm ô tick trông y hệt nhau và người
        // dùng không biết mình đang tick cái nào.
        const due = shortDue(item.due_date);
        const label = due ? `${item.title} · ${due}` : item.title;
        return { label: label.slice(0, 100), value: String(item.task_id) };
      }),
      { multiple: true }
    );
    form.button(actionId("review_submit", notificationId || "-"), "✓ Xác nhận", STYLE.SUCCESS);
  }

  return form.build();
}

/**
 * Kết quả sau khi bấm Xác nhận.
 *
 * Không tick gì mà vẫn bấm là một câu trả lời hợp lệ — *"tôi xem rồi, đúng
 * như thế"* — nên nó được xác nhận đàng hoàng chứ không bị coi là thao tác
 * thừa. Thẻ mới không mang `components`, nên không ai bấm lại lần hai được.
 */
function renderReviewApplied({ updated = [], failed = [], doneCount, totalCount }) {
  if (!updated.length && !failed.length) {
    return notice("🌙 Đã xác nhận", "Không có thay đổi nào — giữ nguyên như trên.", {
      color: "#8b949e",
    });
  }

  const parts = [];
  if (updated.length) {
    parts.push(
      `Đã đánh dấu xong ${updated.length} việc:\n` +
        updated.map((t) => `✅ ${t}`).join("\n")
    );
  }
  if (failed.length) {
    // Nói rõ cái nào hỏng thay vì báo "một số việc không cập nhật được":
    // việc lặp theo sự kiện trả 422 cho một lệnh ghi trần và cần chọn lần
    // lặp, thứ không hỏi được trong một thao tác gộp.
    parts.push(
      `Chưa cập nhật được ${failed.length} việc:\n` +
        failed.map((t) => `⚠️ ${t}`).join("\n") +
        "\nMở Cortex hoặc gõ `*today` để xử lý riêng từng việc."
    );
  }
  if (typeof doneCount === "number" && typeof totalCount === "number") {
    parts.push(`Hôm nay: ${ratioLine(doneCount, totalCount)}`);
  }

  return notice("🌙 Đã cập nhật", parts.join("\n\n"), {
    color: failed.length ? "#d29922" : "#238636",
  });
}

module.exports = {
  OPEN_FIELD_ID,
  MAX_LISTED,
  renderDayReview,
  renderReviewApplied,
  ratioLine,
};
