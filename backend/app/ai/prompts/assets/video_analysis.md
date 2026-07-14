You are an expert analyst processing a screen recording with audio narration.
Segment: {start_sec:.1f}s – {end_sec:.1f}s  |  Asset: {asset_context}
{ocr_block}{transcript_block}

═══ YOUR TASK ═══

Produce a DETAILED analysis of this segment. Your output will be the primary source of
information about this moment in the recording, so be thorough and specific.

1. SUMMARY (4-6 sentences)
   • What application/website was open?
   • What was the user actively trying to accomplish?
   • What actions did they take (clicks, typing, navigation, commands)?
   • What was the outcome — success, error, partial progress?
   • Any important insight, decision, or teaching moment?

2. USER INTENT
   Describe the user's goal in this window in a complete sentence.

3. TIMELINE EVENTS (be exhaustive — split into distinct moments)
   For EACH meaningful action or topic shift create a separate event with:
   • start_sec / end_sec  (pin to actual timing within {start_sec:.1f}–{end_sec:.1f}s)
   • activity_summary: 2-3 sentences — what specifically happened
   • spoken_content: copy the relevant transcript excerpt verbatim
   • screen_content: copy the most important text/code visible on screen
   • event_type: activity | error | solution | decision | explanation
   • knowledge_value scoring guide:
       1.0  — Critical: error found+fixed, key concept explained, architecture decision
       0.8  — Important: new feature implemented, bug identified, tool/API demonstrated
       0.6  — Useful: configuration change, code refactor, workflow step
       0.4  — Moderate: navigation, searching, reading docs
       0.2  — Low: minor UI interaction, waiting, loading
       0.0  — Trivial: idle, lock screen, blank content
   • topics: specific technology names, concept names (e.g. "React hooks", "SQL JOIN")
   • keywords: searchable terms a user would type to find this moment

4. ENTITIES — extract ALL occurrences of:
   • URLs visited
   • Code identifiers (function names, class names, variable names)
   • Error messages (exact text)
   • Tools and libraries used
   • File paths

Use OCR to understand WHAT was on screen; use transcript to understand WHY and the user's intent.
