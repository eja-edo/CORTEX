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
dependencies:
  - memory
  - research
---

## PLAN SKILL

The Plan skill turns a want into a structured, actionable plan. It is NOT just
calendar management — it is goal planning. Use it whenever the user expresses
a goal, desire, or long-term intention.

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

When the user states a want ("Tôi muốn X"), follow this FIXED order — it is
the same flow as the system prompt. Do not propose the full plan before the
critical facts, and do not keep asking after they are known.

1. **DETECT** — Name the goal type (learning, business, health, exam, skill).
2. **CHECK** — Search memory/notes/schedules for existing context. Never ask
   for something you can already know.
3. **ASK only critical facts** — The minimum needed to plan correctly:
   - Learning: mục tiêu (IELTS/TOEIC/Giao tiếp/Công việc) + mốc thời gian
     (3/6/12 tháng)
   - Health: timeframe (3/6 tháng) + current routine
   - Business: loại hình + vốn dự kiến + địa điểm (nếu có)
   - Exam: target score + deadline
   Always as concrete options with a recommended default, max 1-3 questions.
   Never open questions ("Bạn muốn học thế nào?").
4. **PLAN** — Once the critical facts are known (or user says "tùy bạn"),
   present phases → milestones → schedule → checklist → review compactly.
5. **CONFIRM** — "Áp dụng luôn?" / "Bạn muốn điều chỉnh gì?"
6. **ACT** — Once approved, save the plan to a note, schedule the milestones,
   and set reminders.

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
