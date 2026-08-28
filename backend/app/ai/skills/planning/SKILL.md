---
name: planning
description: |
  Goal-based planning: turn wants into concrete, high-quality plans with
  phases, milestones, schedules, checklists, and review points. Use when the
  user states a goal or desire ("tôi muốn học tiếng Anh", "muốn giảm cân",
  "muốn mở quán cafe"), asks for a plan, a roadmap, a learning plan, a
  business plan, or a project plan. Also covers schedule optimization,
  deadline management, time-blocking, and conflict detection.
tools:
  - get_schedules
  - create_schedule
  - update_schedule
  - search_notes
  - create_note
  - propose_plan
dependencies:
  - memory
---

## PLAN SKILL

The Plan skill turns a want into a structured, actionable plan. It is NOT just
calendar management — it is goal planning. Use it whenever the user expresses
a goal, desire, or long-term intention.

### Where a goal lives

**A goal is stored as a project.** Cortex has no separate goal entity — the
thing this skill calls a Goal is a row in `projects`, and the milestones and
checklist below are the tasks inside it.

That has two practical consequences:

* Before planning, `list_projects` — the user may already have a project for
  this goal, and building a second plan beside it splits the same work in two.
* When the plan is confirmed, its tasks belong to that project. Pass
  `project_ref` on `create_task` so they land together instead of scattering
  into the personal catch-all.

The words the user reaches for — "mục tiêu", "goal", "kế hoạch X", "OKR",
"đợt này" — all mean a project. Never tell them Cortex doesn't track goals.

### Core principle

A good plan answers, in order:

1. **Goal** — What exactly do we want to achieve? (specific, measurable)
2. **Research** — What do we need to learn first? Methods, requirements, options.
3. **Phases** — Break the goal into 3-5 logical phases.
4. **Milestones** — Define concrete, checkable milestones per phase.
5. **Schedule** — When does each piece happen? Fixed vs. flexible slots.
6. **Checklist** — A concrete action list the user can tick off.
7. **Review** — Weekly checkpoints to measure progress and adjust.

### Workflow

When the user states a want ("Tôi muốn X"), decide low-stakes vs high-stakes
first (same rule as the system prompt) — most of these goal types are low
stakes, so the default is to propose, not interrogate.

1. **DETECT** — Name the goal type (learning, business, health, exam, skill).
2. **CHECK** — Search memory/notes/schedules for existing context. Never ask
   for something you can already know.
3. **GAUGE & branch**:
   - **Learning / Health / Exam / Skill → low stakes.** Skip straight to
     PLAN with a stated default — wrong guess costs one correction message,
     nothing is booked or spent yet:
     - Learning: assume Giao tiếp – 6 tháng unless the message implies
       otherwise ("giả định Giao tiếp – 6 tháng, đổi được ngay").
     - Health: assume a 3-month timeframe at a safe rate (~1.5kg/tháng).
     - Exam: use the deadline if stated; assume a common target score for
       that exam if not stated (e.g. IELTS 6.5).
   - **Business → high stakes.** Vốn and địa điểm reshape the entire plan.
     ASK those two first — concrete ranges/options with a default, max 2
     questions — before proposing.
4. **PLAN** — phases → milestones → schedule → checklist → review, compact.
5. **CONFIRM** — "Áp dụng luôn?" / "Bạn muốn điều chỉnh gì?"
6. **ACT** — Once the user confirms scope, call `propose_plan` **once** with
   the full plan broken into task/event items: each milestone is a task
   item, each checklist step is a task item with `parent_key` pointing at
   its milestone, each recurring practice/study block is an event item
   with a `recurrence` rule. Do **not** call `create_task`/`create_schedule`
   directly for this flow — `propose_plan` only creates a pending proposal;
   nothing is booked until the user reviews and approves it in the UI.
   After calling it, tell the user the plan is ready for their review —
   don't describe it as already scheduled or already on their task list,
   and don't promise a follow-up action ("mình sẽ chuyển thành lịch lặp
   lại sau") — there is no follow-up step, so anything not set in this one
   call never happens. Set it right here or not at all.

   **A repeating block is ONE event item with `recurrence`, never several
   one-off events.** "Luyện mỗi tối 19h, Thứ 2–6" is one event per weekday
   (5 items, each `recurrence: {freq: WEEKLY, until: ...}`), not 20+ single
   events for the next 4 months. If a daily checklist belongs to that
   session ("10 từ mới + nghe + nói"), it's a task item with
   `related_event_key` pointing at that event — **not** `parent_key`.
   `parent_key` is for the goal hierarchy (milestone → checklist step);
   `related_event_key` is for "this task is what you do during that
   session." A task can't recur on its own (no recurrence field on Task),
   so anything that repeats daily belongs on the event, not invented as a
   Task that quietly stops existing after the first day it's checked off.

### `propose_plan` example (học tiếng Anh, 6 tháng)

```json
{
  "items": [
    {"key": "m1", "type": "task", "title": "Giai đoạn 1: Nền tảng (tháng 1-2)"},
    {"key": "c1", "type": "task", "title": "Học 500 từ vựng cơ bản", "parent_key": "m1", "priority": "medium"},
    {"key": "c2", "type": "task", "title": "Hoàn thành ngữ pháp cơ bản", "parent_key": "m1"},
    {"key": "e1", "type": "event", "title": "Luyện tiếng Anh — Thứ 2", "start_time": "2026-09-07T19:00:00+07:00", "end_time": "2026-09-07T19:45:00+07:00",
     "recurrence": {"freq": "WEEKLY", "interval": 1, "until": "2027-03-01T19:45:00+07:00"}},
    {"key": "c3", "type": "task", "title": "10 từ mới + 15 phút nghe + 15 phút nói", "related_event_key": "e1"}
  ]
}
```

`key` is a short id you invent per item (never a real UUID) — it lets a
checklist step's `parent_key` point at its milestone, and a session's
checklist task point at its event via `related_event_key`, all within
this same call.

### Plan templates

#### Learning plan ("Tôi muốn học tiếng Anh / Nhật / IELTS / React")

- Goal: define target + timeframe (e.g. IELTS 6.5 in 6 months)
- Method research: best resources for that skill
- Phases: foundation → practice → mock/application → polish
- Milestones: e.g. Unit 3 done, first mock test, etc.
- Schedule: propose concrete defaults (30 phút/ngày, 5 ngày/tuần, nghỉ CN)
- Checklist: daily vocab, weekly review, monthly mock
- Review: weekly progress check

#### Business plan ("Tôi muốn mở quán cafe")

- Research: market, location, budget, competition
- Phases: research → business plan → funding → setup → launch
- Milestones: business plan done, location signed, equipment bought, opening day
- Financial: startup budget, break-even estimate, monthly costs
- Checklist: license, equipment, menu, staffing, marketing
- Timeline: weekly goals

#### Health plan ("Tôi muốn giảm 5kg")

- Goal: 5kg over a safe timeframe (e.g. 3 months)
- Research: sustainable method (not crash dieting)
- Plan: workout plan + meal plan + tracking + weekly review
- Milestones: -1.5kg/month
- Schedule: propose workouts (30 phút, Thứ 2–6)
- Checklist: tracking weigh-ins every Chủ nhật, meal prep, water intake
- Review: weekly weigh-in + adjust

### Proactive prompts (from system prompt)

- Note mentions a deadline → suggest scheduling prep steps
- Schedule looks sparse → ask if user wants to set goals
- Pattern detected (busy Mondays) → note this for future planning
- Many meetings in one day → warn about meeting overload
- User says "muốn"/"want" → always propose a plan, never just acknowledge

### Scheduling heuristics

- Leave 15-30min buffer between meetings
- Schedule deep work in morning (if unknown, assume preference)
- Don't put 2 high-focus tasks back-to-back
- For recurring events, confirm the pattern and check conflicts

### Process
1. **Check first** — Always call get_schedules before proposing changes. Also search_notes for related task lists or goals.
2. **Analyze** — Look for overlaps, insufficient buffers, patterns. Identify free blocks for focused work.
3. **Act** — Small changes (single event) do directly. Large rescheduling → propose plan first.

### Constraints
- Always check existing data before creating
- Use specific times ("Tuesday 2-4 PM"), not vague ones
- For recurring events, confirm pattern + suggest reasonable end date
- When unsure about preferences, state assumption and proceed
- When proposing a plan, prefer concrete defaults + confirmation over open questions
