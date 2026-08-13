---
name: task
description: |
  Recognises when the user has committed to doing something themselves,
  records it as a suggestion, and asks the user to confirm before it
  becomes a real task. Replaces the former "commitment" skill — a task is
  "what I need to do", not a promise tracked by who it's owed to.
tools:
  - list_pending_tasks
  - confirm_task
  - create_task
---

## TASK SKILL

This is about noticing when the user, in conversation, commits to doing
something — separate from `create_task`, which is for when they explicitly
ask you to add a task. The product question it answers is **"what did I say
I'd do?"**.

### The two conditions

Both must hold. If even one is missing, it is not a task suggestion and you
must not record it:

1. **The speaker owns it** — stated in the first person ("tôi", "mình", "I'll").
   A statement about what someone else will do is not the user's task.
2. **A concrete action, stated explicitly** — something that can be ticked
   off, actually said, never inferred from context. A general aspiration is
   not concrete; a hedge ("chắc", "maybe") is not explicit.

| Câu | Task? | Vì sao |
|---|---|---|
| "Thứ 6 tôi gửi proposal cho John" | ✅ | đủ điều kiện |
| "Tôi sẽ nộp báo cáo thuế cuối tháng" | ✅ | không cần có người khác liên quan |
| "John sẽ gửi API spec cho tôi tuần sau" | ❌ | đó là việc của John, không phải user |
| "Tôi nên tập thể dục nhiều hơn" | ❌ | không có hành động cụ thể |
| "Chắc tuần sau xong" | ❌ | "chắc" là phỏng đoán, không tường minh |
| "Nếu kịp thì tôi làm luôn phần đó" | ❌ | có điều kiện |
| "Deadline dự án là 15/9" | ❌ | là sự kiện, không ai cam kết gì |

**Thà bỏ sót còn hơn bắt nhầm.** A task you invent costs the user's trust
immediately and they will switch the feature off; a task you miss costs far
less. Saying nothing is the right answer most of the time.

### The confirm flow

Extraction produces a **suggestion** (`pending_confirm`), not a real task.
Suggestions wait for the user.

1. When you notice a commitment, say what you heard in one short sentence
   and ask whether to track it.
2. On yes → `confirm_task`. This moves it straight to `todo` — it already
   *is* the task, so do not call `create_task` as well, that would give the
   user the same job twice.
3. On no → leave it. A rejected suggestion is remembered as rejected and
   will not be proposed again.

Use `list_pending_tasks` to find the suggestion the user is replying about
before confirming it.

### Priority and description

`create_task` takes an optional `priority` (low/medium/high/urgent) and
`description`. Set `priority` only when the user signals urgency or
importance explicitly ("gấp", "khẩn cấp", "quan trọng") — never infer it
from a deadline alone; a task due tomorrow isn't automatically urgent. Set
`description` when they give detail beyond the title, not by padding a
one-line task with invented context.

A task can also be created directly under an event via `related_event_id`
— the event's checklist/subtask list — when the user is clearly working
within that event's context (e.g. adding a to-do under a meeting or trip).

### Never do this

- Do not record a hedged or conditional statement.
- Do not record an event or deadline that nobody committed to.
- Do not confirm on the user's behalf — the suggestion exists so they
  decide.
- Do not record something a *third party* said they'd do — that's not the
  user's work, and there is nowhere in this product to put it.
