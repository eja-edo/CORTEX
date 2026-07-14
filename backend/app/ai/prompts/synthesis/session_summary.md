You are synthesizing a complete knowledge report for a {asset_type_desc}.

Title: {asset_title}
Duration: {duration_sec:.0f}s ({duration_sec/60:.1f} minutes)
Windows analyzed: {window_count}
Total timeline events: {total_events}

─── WINDOW-BY-WINDOW SUMMARY ───
{windows_block}

─── NOTABLE EVENTS (kv >= 0.4) ───
{events_block}

═══ SYNTHESIS INSTRUCTIONS ═══

Your output is the PERMANENT knowledge record of this session. It must be:
  • Complete — someone who has never seen the recording should understand what happened
  • Accurate — only include things that actually occurred
  • Useful — written so the user can search, review, and learn from it later

1. SESSION TITLE
   A specific, descriptive title (not generic) — e.g. "Debugging Docker Compose
   networking issue in FastAPI app" not "Coding session".

2. OVERALL SUMMARY (5-8 sentences)
   Cover: What was the goal? What approach was used? What went well?
   What problems occurred and how were they resolved? What was the end state?
   What are the key takeaways?

3. PRIMARY + SECONDARY TECHNOLOGIES
   List every technology, framework, library, tool, platform that appeared.

4. DIFFICULTY LEVEL
   beginner / intermediate / advanced based on the content's technical depth.

5. WORKFLOW (ordered steps)
   Break the session into its logical phases/steps, each with start_sec/end_sec.
   Be specific — "Installed dependencies and configured environment (0s–180s)"
   not "Set up project".

6. PROBLEMS ENCOUNTERED
   Every problem, error, blocker, or confusion — include:
   • Exact error message if available
   • Context (what they were trying to do)
   • Resolution (what fixed it, or "unresolved")
   • Approximate time to resolve

7. SOLUTIONS FOUND
   Every successful fix, workaround, or discovery — include the specific solution
   and how reusable/generalizable it is (0.0=very specific, 1.0=universally applicable).

8. KNOWLEDGE GAINED
   An EXHAUSTIVE list of distinct learnings — every concept, technique, and insight.
   Write each as a complete sentence starting with an action verb:
   "Learned that...", "Discovered that...", "Demonstrated how to...", etc.
   Aim for at least one item per 2-3 minutes of content.

9. KEY QUOTES
   The 3-8 most important things said (verbatim or near-verbatim).
   These should be the statements that best capture the session's insights.

10. KNOWLEDGE TIMELINE (MOST IMPORTANT)
    The complete, ordered timeline of ALL notable moments.
    Include EVERY event with knowledge_value >= 0.3.
    For audio sessions: include every distinct topic, explanation, and decision.
    For video sessions: include every meaningful screen state change + speech.
    Each entry must have:
    • start_sec, end_sec (precise timing)
    • activity_summary: 2-3 sentences fully describing the moment
    • spoken_content: key verbatim excerpt (if audio available)
    • screen_content: key visible text (if video available)
    • event_type: activity | error | solution | decision | explanation
    • knowledge_value: 0.0–1.0
    • topics: specific subjects
    • keywords: searchable terms

    The timeline should be dense enough that the user can reconstruct the
    entire session from it — aim for one entry per 30-60 seconds of content.
