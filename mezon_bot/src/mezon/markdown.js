"use strict";

/**
 * The AI's text, unmodified, as Mezon message content.
 *
 * This file used to parse the AI's Markdown into a real syntax tree
 * (`unified`/`remark-parse`/`remark-gfm`) and translate that into Mezon's
 * `mk` style ranges plus `InteractiveBuilder` embed fields for tables —
 * see git history (`markdown.js`, `tableRender.js`, `embed.js`'s
 * `withTableEmbeds`) for that whole approach. It correctly handled every
 * construct it was tested against, including several real bugs found
 * along the way, but the net result — bold/heading/list/table markdown
 * silently rewritten into Mezon's own narrower vocabulary — still didn't
 * read as "the AI's actual answer" once it was in front of a real user:
 * tables became a visually separate card, headings/italics collapsed to
 * plain bold, and every rendering choice was a judgment call about what
 * the AI "meant" rather than what it wrote. The simpler, safer choice is
 * to send exactly what the model produced and let it speak for itself —
 * this file's only remaining job is staying under Mezon's hard per-
 * message character cap, which is a wire limit, not a rendering choice.
 */

// `writeChatMessage` in mezon-sdk throws once `JSON.stringify(content).
// length` passes 4000 — left with a safety margin under that hard cap.
const MAX_CONTENT_CHARS = 3500;

/** `markdown` → `{ t }`, verbatim — `t` is `send`/`update`'s first
 *  (`content`) argument as-is. Assumes the result fits in one message;
 *  `splitMezonContent` is the entry point for anything that might not. */
function toMezonContent(markdown) {
  return { t: markdown ?? "" };
}

/**
 * Splits `markdown` into as many `{ t }` chunks as needed to stay under
 * Mezon's per-message character cap — the one thing this file still has
 * to get right now that it does no other transformation. Cuts at the
 * last newline within budget so a chunk boundary doesn't land mid-line;
 * a single line longer than the whole budget is cut at the character
 * limit itself rather than held back, since `mezon-sdk`'s own hard error
 * on an oversized message is a worse outcome than a mid-line split.
 */
function splitMezonContent(markdown, maxChars = MAX_CONTENT_CHARS) {
  const raw = markdown ?? "";
  if (!raw) return [{ t: "" }];

  const chunks = [];
  let start = 0;
  while (raw.length - start > maxChars) {
    const hardEnd = start + maxChars;
    const lastNewline = raw.lastIndexOf("\n", hardEnd);
    const cutAtNewline = lastNewline > start;
    const end = cutAtNewline ? lastNewline : hardEnd;
    chunks.push({ t: raw.slice(start, end) });
    start = cutAtNewline ? end + 1 : end; // skip the newline itself when it was the cut point
  }
  chunks.push({ t: raw.slice(start) });
  return chunks;
}

module.exports = { toMezonContent, splitMezonContent };
