---
name: research
description: |
  Multi-step web research, deep-dive analysis, fact-checking,
  information synthesis, and structured reporting on any topic.
tools:
  - web_search
  - web_fetch
dependencies: []
---

## RESEARCH SKILL

Relevant tools: web_search (find sources), web_fetch (read full pages)

### Process
1. **Plan** — Break topic into sub-questions. Identify what type of info is needed (facts, comparisons, recent data, analysis).
2. **Search** — Start broad with web_search (max_results=10). Then narrow with specific queries for gaps. Try different phrasings.
3. **Read** — Use web_fetch on top 2-3 results (not just snippets). Cross-reference claims across sources.
4. **Synthesize** — Identify patterns, consensus, disagreements. Distinguish established facts from emerging info.

### Tips
- For time-sensitive topics, check publication dates explicitly
- Prefer sources <2 years old unless historical context is needed
- If initial search is weak, try 2-3 alternative query phrasings before concluding
- When sources disagree, present both sides with your assessment
- After research, suggest related questions the user might want to explore

### Multi-source synthesis pattern
Research question → search broadly → read deeply → identify themes → note conflicts → state confidence → suggest next steps

### Constraints
- Never fabricate or guess — if sources are insufficient, state this clearly
- Never call web_search with the same query twice
- Always cite specific sources with [title] when presenting findings
