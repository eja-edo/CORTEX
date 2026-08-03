---
name: goal
description: |
  Long-term goal tracking. Detects when the user states a goal or want, keeps
  the goal's plan/checklist/milestones up to date, and reacts to progress
  reports by updating progress instead of just congratulating.
tools:
  - search_notes
  - create_note
  - update_note
  - get_schedules
  - create_schedule
  - extract_memory
dependencies:
  - memory
  - planning
---

## GOAL SKILL

The Goal skill owns long-term goals: detection, tracking, and progress updates.

### Goal detection

Treat these as goal statements (not mere narration):

- "Tôi muốn giảm 5kg." / "Tôi muốn học tiếng Anh."
- "Tháng sau tôi thi IELTS." / "Cuối năm tôi muốn mở quán cafe."
- "Tôi muốn chạy marathon." / "Tôi muốn học AI."

For every detected goal:

1. Search memory + notes for existing goal context ("Mình có kế hoạch cho
   mục tiêu này chưa?")
2. Propose a plan (see planning skill) — phases, milestones, schedule,
   checklist, review.
3. Track the goal in a note + set milestone reminders.

### Progress report handling

When the user reports completion, UPDATE — do not just congratulate.

- "Hôm nay tôi học xong Unit 3." → search checklist → tick Unit 3 → show
  progress (3/20 units) → suggest next step.
- "Tôi vừa gửi CV." → complete task → update job goal → remove old reminder →
  create follow-up reminder (e.g. follow up in 5 days).
- "Tôi vừa thanh toán tiền điện." → mark bill paid → remove reminder.
- "Tôi chạy được 5km." → update workout log → update goal progress → update streak.

### Workflow

1. **Search** memory/notes/schedules for the related goal or checklist.
2. **Match** the progress report to the concrete item (Unit 3, CV, bill, 5km).
3. **Update** the item: tick, mark done, update progress value.
4. **React** with a meaningful response: current progress %, what's next, any
   reminder to remove/create.
5. If no matching goal/checklist is found: ask (with options) whether this
   relates to a known goal, or offer to start tracking one.

### Ambiguous statements

For vague reports, search context before responding:

- "Cuối cùng cũng xong." → search recent active tasks → confirm which one.
- "Đã gửi rồi." → search recent discussion (invoice/proposal/CV) → confirm.

### Constraints
- Never invent a checklist that doesn't exist — if there's no goal in context, say so
- Always search memory before assuming which goal a progress report refers to
- Preserve streak/progress numbers exactly as found; don't fabricate values
- Mutating actions (ticking, updating) require the item to exist and match
