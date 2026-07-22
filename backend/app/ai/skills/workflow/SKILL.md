---
name: workflow
description: |
  Automating multi-step processes, creating integrations
  between tools, designing and debugging workflow pipelines.
tools:
  - search_notes
  - create_note
  - get_schedules
  - create_schedule
dependencies:
  - planning
---

## WORKFLOW SKILL

Relevant tools: search_notes / create_note (data), get_schedules / create_schedule (time-based)

### When to suggest a workflow
The user would benefit from automation when they:
- Perform the same multi-step task repeatedly
- Need info collected, processed, and stored regularly
- Want a notification to trigger follow-up actions
- Need data synchronized between note + schedule

### Common Cortex automation patterns
- **Deadline → Schedule**: note mentions deadline → auto-create calendar event
- **Research → Save**: web search → summarize → save to note
- **Schedule change → Alert**: conflict detected → notify user
- **Periodic → Report**: daily/weekly summary generation
- **Note + Schedule sync**: update note when schedule changes

### Design approach
1. Map the complete process before suggesting automation
2. Identify: trigger → steps → outcome
3. Consider error handling: what if a step fails?
4. Start simple, add complexity iteratively

### Constraints
- Explain what the workflow will do before creating it
- Start simple, enhance iteratively
- Flag irreversible actions in the design
- Don't create noisy workflows — respect notification preferences
- For complex workflows, suggest testing with a manual dry-run first
