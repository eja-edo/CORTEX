"use strict";

/**
 * Thẻ tổng kết cuối ngày — tỷ lệ, trạng thái tick, và nút Xác nhận.
 *
 * Ba tính chất đáng khoá, cả ba đều dễ hỏng theo kiểu vẫn trông như chạy:
 *
 * 1. **Chỉ việc chưa xong mới bấm được.** Radio của Mezon không có trạng
 *    thái chọn sẵn, nên đưa việc đã xong vào nhóm chọn sẽ khiến người dùng
 *    bỏ tick một việc đã xong, bấm Xác nhận, và *tưởng* mình vừa mở lại
 *    nó — trong khi không có gì xảy ra.
 * 2. **Nút sống sót qua restart.** Id các việc được tick quay về trong
 *    `values`, nên thẻ không phụ thuộc `pendingForms` (TTL 30 phút, mất khi
 *    restart) — đúng yêu cầu của một DM nằm trong chat qua đêm.
 * 3. **Một việc hỏng không nuốt phần còn lại**, và cái hỏng phải được nói
 *    ra tên.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { MessageRouter } = require("../src/router");
const { CommandRegistry } = require("../src/commands/registry");
const { notification } = require("../src/mezon/embed");
const { parseActionId } = require("../src/mezon/actions");
const { OPEN_FIELD_ID } = require("../src/mezon/reviewCard");

function makeRouter(cortex) {
  const sent = [];
  const edits = [];
  const gateway = {
    sendToChannel: async (channelId, content) => {
      sent.push({ channelId, content });
      return { id: "m1" };
    },
    editMessage: async (channelId, messageId, content) => {
      edits.push({ channelId, messageId, content });
      return { id: messageId };
    },
  };
  const router = new MessageRouter({
    gateway,
    registry: new CommandRegistry({ prefix: "*" }),
    cortex,
    prefix: "*",
    timezone: "Asia/Ho_Chi_Minh",
  });
  return { router, sent, edits };
}

const linked = { resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }) };

function buttonEvent(buttonId, values) {
  return {
    button_id: buttonId,
    message_id: "card-msg",
    channel_id: "ch-1",
    user_id: "mezon-u1",
    sender_id: "bot-id",
    extra_data: values === undefined ? "" : JSON.stringify(values),
  };
}

const reviewPayload = {
  completed_today_count: 3,
  open_task_count: 2,
  overdue_task_count: 1,
  completed_today: [
    { task_id: "d1", title: "Viết đề cương" },
    { task_id: "d2", title: "Gửi spec" },
    { task_id: "d3", title: "Review PR" },
  ],
  still_open: [
    { task_id: "o1", title: "Chốt scope" },
    { task_id: "o2", title: "Đặt lịch họp" },
  ],
};

function buildReview(payload = reviewPayload) {
  return notification({
    title: "Tổng kết cuối ngày",
    body: "Xong 3 việc hôm nay · còn 2 việc chưa xong",
    attention_level: "inform",
    reason_key: "day.review",
    notification_id: "notif-9",
    payload,
  });
}

const dump = (content) => JSON.stringify(content);
const buttonsOf = (content) => content.components?.[0]?.components ?? [];

// ── Hiển thị ─────────────────────────────────────────────────────────────

test("tỷ lệ đứng trước danh sách — cuối ngày người ta hỏi 'đi được bao xa'", () => {
  const text = dump(buildReview());
  assert.match(text, /Xong 3\/5 việc/);
  assert.match(text, /60%/);
});

test("việc đã xong hiện dạng đã tick trong phần chữ", () => {
  const text = dump(buildReview());
  assert.match(text, /✅ Viết đề cương/);
  assert.match(text, /✅ Gửi spec/);
});

test("việc chưa xong KHÔNG lặp lại trong phần chữ — chúng đã là ô tick", () => {
  // In hai lần bắt người đọc lướt qua cùng danh sách hai lượt rồi tự đối
  // chiếu xem hai bản có khớp nhau không. Ô tick là bản có thẩm quyền.
  const embed = buildReview().embed[0];
  assert.doesNotMatch(embed.description, /Chốt scope/);
  const radio = embed.fields.find((f) => f.name === "Chưa xong — tick việc bạn đã làm");
  assert.ok(radio.inputs.component.some((o) => o.label.startsWith("Chốt scope")));
});

test("description không dùng markdown — Mezon nuốt cả nội dung trong **…**", () => {
  // Thẻ đầu tiên gửi đi in ra "việc — 17%" vì `**2/12**` biến mất sạch.
  assert.doesNotMatch(buildReview().embed[0].description, /\*\*/);
});

test("việc quá hạn được gọi tên riêng, không trộn vào 'chưa xong'", () => {
  assert.match(dump(buildReview()), /1 việc đã quá hạn/);
});

test("chỉ việc chưa xong vào nhóm chọn được", () => {
  const built = buildReview();
  const radio = built.embed[0].fields.find((f) => f.name === "Chưa xong — tick việc bạn đã làm");
  const values = radio.inputs.component.map((o) => o.value);
  assert.deepEqual(values, ["o1", "o2"]);
});

test("hạn đi kèm nhãn — nhiều việc trùng tên chỉ khác ngày", () => {
  // Năm việc tên "10 từ mới…" khác nhau đúng ở due_date. Không có hạn
  // trên nhãn thì năm ô tick trông y hệt nhau.
  const built = buildReview({
    ...reviewPayload,
    still_open: [
      { task_id: "o1", title: "10 từ mới", due_date: "2026-08-26T13:45:00+00:00" },
      { task_id: "o2", title: "10 từ mới", due_date: "2026-08-27T13:45:00+00:00" },
    ],
  });
  const radio = built.embed[0].fields.find((f) => f.name === "Chưa xong — tick việc bạn đã làm");
  const labels = radio.inputs.component.map((o) => o.label);
  assert.notEqual(labels[0], labels[1]);
  assert.match(labels[0], /26\/08/);
  assert.match(labels[1], /27\/08/);
});

test("nút Xác nhận mang id tự mô tả, không phải một khoá trong bộ nhớ", () => {
  const [button] = buttonsOf(buildReview());
  assert.deepEqual(parseActionId(button.id), {
    kind: "review_submit",
    targetId: "notif-9",
  });
});

test("không còn việc mở thì không có nút nào để bấm", () => {
  const built = buildReview({
    ...reviewPayload,
    open_task_count: 0,
    still_open: [],
  });
  assert.equal(built.components, undefined);
  assert.match(dump(built), /Xong 3\/3 việc/);
});

// ── Xác nhận ─────────────────────────────────────────────────────────────

test("bấm Xác nhận hoàn thành đúng những việc được tick", async () => {
  const completed = [];
  const cortex = {
    ...linked,
    completeTask: async (taskId, userId) => {
      completed.push({ taskId, userId });
      return { id: taskId, title: taskId === "o1" ? "Chốt scope" : "Đặt lịch họp" };
    },
  };
  const { router, edits } = makeRouter(cortex);

  await router.handleButton(buttonEvent("rs:notif-9", { [OPEN_FIELD_ID]: ["o1", "o2"] }));

  assert.deepEqual(completed, [
    { taskId: "o1", userId: "cortex-u1" },
    { taskId: "o2", userId: "cortex-u1" },
  ]);
  const text = dump(edits[0].content);
  assert.match(text, /Đã đánh dấu xong 2 việc/);
  assert.match(text, /Chốt scope/);
});

test("xác nhận mà không tick gì là một câu trả lời hợp lệ, không phải thao tác thừa", async () => {
  let wrote = false;
  const cortex = { ...linked, completeTask: async () => { wrote = true; } };
  const { router, edits } = makeRouter(cortex);

  await router.handleButton(buttonEvent("rs:notif-9", { [OPEN_FIELD_ID]: [] }));

  assert.equal(wrote, false);
  assert.match(dump(edits[0].content), /Không có thay đổi nào/);
});

test("một việc hỏng không nuốt phần còn lại, và nó được gọi tên", async () => {
  // Việc lặp theo sự kiện trả 422 cho một lệnh ghi trần vì nó cần biết lần
  // lặp nào — câu hỏi không hỏi được trong một thao tác gộp.
  const cortex = {
    ...linked,
    completeTask: async (taskId) => {
      if (taskId === "o1") throw new Error("422 occurrence required");
      return { id: taskId, title: "Đặt lịch họp" };
    },
  };
  const { router, edits } = makeRouter(cortex);

  await router.handleButton(buttonEvent("rs:notif-9", { [OPEN_FIELD_ID]: ["o1", "o2"] }));

  const text = dump(edits[0].content);
  assert.match(text, /Đã đánh dấu xong 1 việc/);
  assert.match(text, /Đặt lịch họp/);
  assert.match(text, /Chưa cập nhật được 1 việc/);
  assert.match(text, /o1/);
});

test("thẻ kết quả không mang nút nào — không ai xác nhận được hai lần", async () => {
  const cortex = { ...linked, completeTask: async (id) => ({ id, title: "x" }) };
  const { router, edits } = makeRouter(cortex);

  await router.handleButton(buttonEvent("rs:notif-9", { [OPEN_FIELD_ID]: ["o1"] }));

  assert.equal(edits[0].content.components, undefined);
});
