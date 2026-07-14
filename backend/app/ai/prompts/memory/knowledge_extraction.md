You are extracting structured knowledge units from a recording segment.
Time range: {start_sec:.1f}s – {end_sec:.1f}s
Context: {context}
Sources available: {source_desc}
{ocr_block}{transcript_block}

═══ EXTRACTION INSTRUCTIONS ═══

Extract EVERY piece of reusable knowledge. Be exhaustive — it is better to
include a borderline item than to miss something useful.

FACTS
  • General learnings, techniques, best practices, concepts demonstrated
  • Configuration details, parameter values, settings that matter
  • "I learned that X works like Y" style insights
  • Each fact should be a self-contained, reusable statement
  • Minimum useful length: one clear sentence

ERRORS
  • Every error message shown on screen or mentioned verbally
  • Include the EXACT error text as `message`
  • For `resolution`: what was done to fix it (or "unresolved" if not fixed)
  • Include partial errors — even if not fully resolved, document them

CODE PATTERNS
  • Any code snippet visible on screen or dictated verbally
  • Include enough context to understand the pattern (not just one line)
  • `purpose`: what this code accomplishes

COMMANDS
  • Every CLI/shell/terminal command visible or spoken
  • Include flags and arguments
  • `purpose`: what the command does

EXPLANATIONS
  • Any moment where a concept is explained, defined, or demonstrated
  • Both verbal explanations (from transcript) and implicit demonstrations (from screen)
  • `explanation`: a complete, standalone explanation of the topic

DECISIONS
  • Choices the user made with explicit or implicit reasoning
  • Technology choices, architectural decisions, workaround selections
  • `rationale`: why this choice was made (even if inferred)
  • `alternatives_considered`: other options mentioned or implied

For each item, estimate start_sec/end_sec within [{start_sec:.1f}, {end_sec:.1f}]:
  • Use transcript timing for verbal explanations and decisions
  • Use frame timestamps for screen-based errors and code
  • When uncertain, use the window boundaries

Do NOT skip items because they seem minor — the user may search for them later.
