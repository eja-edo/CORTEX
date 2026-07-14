You are an expert analyst processing a silent screen recording (no audio).
Segment: {start_sec:.1f}s – {end_sec:.1f}s  |  Asset: {asset_context}
{ocr_block}

═══ YOUR TASK ═══

Produce a DETAILED analysis based solely on what was visible on screen.

1. SUMMARY (4-6 sentences)
   • What application or website was open?
   • What content or data was displayed?
   • What was the user apparently trying to do (inferred from screen state)?
   • What changes occurred between frames (new content, errors, navigation)?
   • Any error messages, code, commands, or important text visible?

2. USER INTENT
   Infer the user's goal from the screen content alone.

3. TIMELINE EVENTS (split by meaningful screen changes)
   • start_sec / end_sec within {start_sec:.1f}–{end_sec:.1f}s
   • activity_summary: describe what is shown and what it implies about the user's action
   • spoken_content: leave empty (no audio)
   • screen_content: exact copy of the most important visible text
   • event_type: activity | error | solution | decision | explanation
   • knowledge_value (same scale as above)
   • topics & keywords: derived from visible content

4. ENTITIES — extract ALL visible:
   • URLs in address bars or on screen
   • Error messages (exact text)
   • Code identifiers and snippets
   • File paths, commands visible in terminal
   • Tool/library names visible on screen

Infer as much context as possible from what is shown, but do not fabricate
information that is not present in the OCR text.
