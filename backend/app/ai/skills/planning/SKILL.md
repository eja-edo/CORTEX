---
name: planning
description: |
  Schedule optimization, task planning, deadline management,
  time-blocking, and identifying scheduling conflicts or gaps.
tools:
  - get_schedules
  - create_schedule
  - update_schedule
  - search_notes
dependencies:
  - memory
---

## PLANNING SKILL

Relevant tools: get_schedules (check), create_schedule (add), update_schedule (modify), search_notes (find task lists)

### Process
1. **Check first** — Always call get_schedules before proposing changes. Also search_notes for related task lists or goals.
2. **Analyze** — Look for overlaps, insufficient buffers, patterns. Identify free blocks for focused work.
3. **Act** — Small changes (single event) do directly. Large rescheduling → propose plan first.

### Scheduling heuristics
- Leave 15-30min buffer between meetings
- Schedule deep work in morning (if unknown, assume preference)
- Don't put 2 high-focus tasks back-to-back
- For recurring events, confirm the pattern and check conflicts

### Proactive prompts
- Note mentions a deadline → suggest scheduling prep steps
- Schedule looks sparse → ask if user wants to set goals
- Pattern detected (busy Mondays) → note this for future planning
- Many meetings in one day → warn about meeting overload

### Constraints
- Always check existing data before creating
- Use specific times ("Tuesday 2-4 PM"), not vague ones
- For recurring events, confirm pattern + suggest reasonable end date
- When unsure about preferences, state assumption and proceed
