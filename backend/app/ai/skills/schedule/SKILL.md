---
name: schedule
description: |
  Proactive event scheduling. Use when the user mentions a meeting, an
  appointment, a trip, a flight, a doctor visit, an exam, a deadline, or any
  upcoming event — even without saying "create schedule". Builds reminders,
  preparation checklists, and time blocks around the event.
tools:
  - get_schedules
  - create_schedule
  - update_schedule
  - search_notes
  - create_note
dependencies:
  - memory
  - planning
---

## SCHEDULE SKILL

The Schedule skill is proactive. When the user mentions an event, do not just
create an event — layer the supports around it, then confirm.

### Event detection

The user often does NOT say "tạo lịch". Detect the event from the message:

- "Mai tôi họp với khách." → meeting
- "Mai tôi đi khám bệnh." → doctor visit
- "Tuần sau bay Hà Nội." → flight
- "Thứ Bảy đi Đà Nẵng." → trip
- "Tuần sau nộp proposal." → deadline

### What to build around an event

| Event | Reminders | Preparation | After |
|---|---|---|---|
| Meeting | reminder 15-30 min before | prep block (30 min), meeting checklist | review block |
| Doctor visit | reminder | bring documents: insurance card, medicine list, test results | follow-up note |
| Flight | airport arrival reminder (2-3h), online check-in | packing checklist, taxi reminder, passport | travel notes |
| Trip | departure reminders | book flight, book hotel, packing, currency, SIM card | itinerary note |
| Deadline | reminders at T-7d, T-2d, T-1d | prep steps scheduled | review after submit |

### Workflow

1. **DETECT** the event, date, and what's missing.
2. **CHECK** get_schedules for conflicts and free slots; search history for
   the user's usual time/place/routine ("như mọi khi?").
3. **ASK only the critical missing facts** — for most events this is just the
   start time. Offer time options with a default ("09:00, 09:30, 10:00 hay
   giờ khác?"). If history shows a usual time, ask "09:00 như mọi khi?".
   Defer non-blocking details (địa điểm, thời lượng, ghi chú) — say they can
   be added later.
4. **PROPOSE** the event + the proactive supports the user accepted, e.g.:
   - Meeting → reminder + prep block + meeting checklist + review block
   - Doctor → reminder + bring documents (insurance, medicine list)
   - Flight → airport reminder + check-in + packing + taxi
   Keep the proposal compact; confirm which supports they want.
5. **CREATE** schedule entries and reminders only after confirmation.

### Minimal friction rules

- Ask at most ONE blocking question at a time; the rest can be added later.
- Always offer time options with a default, never "Mấy giờ?".
- When only time is missing: "Mình chỉ cần biết giờ bắt đầu. Còn lại bổ sung sau."

### Constraints
- Always check get_schedules before creating to avoid conflicts
- Use specific times, not vague ones
- For recurring events, confirm the pattern + suggest a reasonable end date
- Never create reminders/checklists the user didn't accept (propose first)
