---
name: memory
description: |
  Managing user context, preferences, and long-term memory.
  Extracting personal information, goals, constraints, and
  behavioral patterns from conversations.
tools:
  - extract_memory
  - search_knowledge
  - search_notes
dependencies: []
---

## MEMORY SKILL

Relevant tools: extract_memory (save), search_knowledge (retrieve), search_notes (find saved info)

### When to extract memory
Call extract_memory when you detect any of these:
- New user preference or constraint ("I prefer mornings", "don't schedule after 6 PM")
- Significant decision with future implications
- Project goal, milestone, or ongoing context
- Recurring behavioral pattern
- Personal context (important dates, relationships, routines)
- User feedback about what's useful or not

### When NOT to extract
- Trivial one-time requests
- Information already stored
- Temporary discussion topics
- Content the user hasn't explicitly owned

### Context retrieval pattern
When user returns to a conversation:
1. Check search_knowledge for relevant past context
2. Check search_notes for related saved info
3. Reference relevant past decisions explicitly ("As we discussed...")
4. Connect related information across notes, schedules, and knowledge

### Cross-referencing
- Note + Schedule: deadline mentioned in note → check if scheduled
- Knowledge + Note: user preference stored → apply when relevant
- Previous + Current: connect current question to past context

### Constraints
- Prefer search_notes / search_knowledge before asking user for info they may have saved
- Transient context (current task) → conversation only
- Stable knowledge (preferences, goals) → extract_memory
- When uncertain about importance, prefer conversation context over permanent storage
