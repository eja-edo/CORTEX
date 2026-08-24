"use strict";

/**
 * The web UI's "Thinking" timeline, rendered for a Mezon message.
 *
 * Parity target is `ToolExecutionIndicator.tsx` + the stream handling in
 * `useAgentStream.ts`, whose behaviour is:
 *
 *   - while the turn is streaming, an expanded timeline shows every
 *     reasoning segment and every tool step, newest last, above the
 *     answer text;
 *   - a `tool_start` "flushes" the reasoning segment in progress — later
 *     reasoning starts a new segment rather than growing the old one;
 *   - tool steps read as human sentences (`search_notes → tìm "abc"`,
 *     then `search_notes 3 kết quả`), not as raw tool names;
 *   - the whole timeline **disappears** when the turn finishes
 *     (`MessageList.tsx` only renders it while `msg.loading`), leaving
 *     just the answer.
 *
 * The one thing the web can do that a Mezon message cannot is collapse:
 * the web hides all of this behind a `▾` toggle, so length costs it
 * nothing. Here the timeline gets its own message (see `router.js`), and
 * the budget below is what keeps a runaway reasoning stream from turning
 * into a wall of chat.
 *
 * **The render is append-only, and that is a correctness property, not a
 * style.** `_syncMultiMessage` seals a chunk the moment a later one
 * appears after it and never edits it again, so a render that rewrote
 * anything already sent — trimming from the front, collapsing an earlier
 * segment, compacting the middle of a long thought — would leave the
 * sealed message showing text that is no longer part of the block. Every
 * bound here therefore cuts from the *end*: entries render in order until
 * the budget runs out, and what does not fit is dropped rather than
 * making room by rewriting what came before.
 */

const HEADER_LIVE = "🧠 **Đang suy nghĩ**";
const HEADER_DONE = "🧠 **Đã suy nghĩ**";

// The whole block, across however many Mezon messages it takes (~3500
// chars each). Two messages' worth of thinking is already far more than
// a turn normally produces; past that the block stops growing rather
// than pushing the answer further and further down the channel.
const MAX_BLOCK_CHARS = 6000;

// Per segment, and deliberately larger than the block budget: text past
// this can never be rendered anyway, so it is dropped on arrival instead
// of being carried around for the life of the turn.
const MAX_STORED_CHARS = 32000;

/** First line with actual words in it, headings stripped — mirrors
 *  `previewContent` in useAgentStream.ts. */
function previewContent(content, maxLen = 60) {
  if (!content || typeof content !== "string") return "";
  const firstLine = content.split("\n").find((l) => l.trim().replace(/^#+\s+/, "")) ?? content;
  return firstLine.replace(/^#+\s+/, "").slice(0, maxLen).trim();
}

/**
 * "What is this call about", from the arguments — a port of
 * `toolSemanticDescription` in useAgentStream.ts. Kept as a copy rather
 * than shared: the bot is a separate deployable with no build step
 * reaching into the frontend, and the two can legitimately diverge (the
 * bot has no note pane to navigate to). Returns "" when the args say
 * nothing worth showing, in which case the caller shows the bare name.
 */
function toolSemanticDescription(toolName, toolArgs) {
  if (!toolArgs) return "";
  const content = toolArgs.content || "";
  const title = toolArgs.title || "";
  const query = toolArgs.query || "";
  const noteId = toolArgs.note_id || "";

  switch (toolName) {
    case "update_note": {
      const preview = previewContent(content);
      return preview ? `note "${preview}"` : "note";
    }
    case "create_note": {
      const preview = previewContent(content);
      const t = title || preview;
      return t ? `note mới "${t}"` : "note mới";
    }
    case "delete_note":
      return "xóa note";
    case "get_note":
      return noteId ? `xem note ${String(noteId).slice(0, 8)}…` : "xem note";
    case "list_notes":
      return title ? `ds notes • ${title}` : "ds notes";
    case "search_notes":
      return query ? `tìm "${query}"` : "tìm notes";
    case "create_schedule":
      return title ? `lịch "${title}"` : "lịch mới";
    case "update_schedule":
      return title ? `cập nhật lịch "${title}"` : "cập nhật lịch";
    case "delete_schedule":
      return "xóa lịch";
    case "revert_action":
      return "(undo)";
    case "web_search":
      return query ? `web search "${query}"` : "web search";
    default:
      return "";
  }
}

/** "How did it go", from the result — a port of `toolResultSummary` in
 *  useAgentStream.ts, same copy-not-share reasoning as above. */
function toolResultSummary(toolName, result, success) {
  const r = result && typeof result === "object" ? result : undefined;
  if (!success) {
    const err = (r && typeof r.error === "string" && r.error) || "thất bại";
    return `✗ ${err.slice(0, 60)}`;
  }
  switch (toolName) {
    case "update_note":
    case "create_note": {
      const v = r?.version;
      const id = typeof r?.id === "string" ? r.id.slice(0, 8) : "";
      return v ? `v${v}${id ? ` • ${id}` : ""}` : "xong";
    }
    case "delete_note":
      return "đã xóa";
    case "search_notes":
    case "list_notes": {
      const count = Array.isArray(r?.notes)
        ? r.notes.length
        : Array.isArray(r?.results)
          ? r.results.length
          : Array.isArray(result)
            ? result.length
            : 0;
      return `${count} kết quả`;
    }
    case "get_note":
      return typeof r?.title === "string" ? `"${r.title.slice(0, 30)}"` : "ok";
    case "create_schedule":
    case "update_schedule": {
      const id = typeof r?.id === "string" ? r.id.slice(0, 8) : "";
      return id ? `id ${id}` : "ok";
    }
    default:
      return "xong";
  }
}

/** Every line of `text` as a Markdown blockquote, so a multi-line thought
 *  reads as one visually separate block instead of blending into the
 *  answer above it. */
function quote(text) {
  return text
    .split("\n")
    .map((line) => `> ${line}`)
    .join("\n");
}

class ThinkingTimeline {
  constructor() {
    this.entries = [];
  }

  isEmpty() {
    return this.entries.length === 0;
  }

  clear() {
    this.entries = [];
  }

  /**
   * A `reasoning_token` arrived. Grows the segment in progress, or opens
   * a new one if the last thing that happened was a tool call — matching
   * `flushPendingThinking()` being called on `tool_start`/`tool_result`
   * in useAgentStream.ts.
   */
  reasoning(text) {
    if (!text) return;
    const last = this.entries[this.entries.length - 1];
    if (last?.kind === "thinking") {
      // Truncated at the end, never compacted in the middle: an earlier
      // version kept the head and the recent tail, which reads better in
      // isolation but rewrites text already sent to a sealed message.
      if (last.text.length >= MAX_STORED_CHARS) return;
      last.text = (last.text + text).slice(0, MAX_STORED_CHARS);
      return;
    }
    this.entries.push({ kind: "thinking", text });
  }

  toolStart(toolName, toolArgs) {
    this.entries.push({ kind: "tool_start", toolName: toolName ?? "", toolArgs });
  }

  toolResult(toolName, { result, success, error } = {}) {
    this.entries.push({
      kind: "tool_result",
      toolName: toolName ?? "",
      result: result ?? (error ? { error } : undefined),
      success: success !== false,
    });
  }

  _line(entry) {
    if (entry.kind === "thinking") {
      const text = entry.text.trim();
      if (!text) return "";
      // In full. A settled segment used to collapse to its opening line,
      // which is what made the Mezon view read as a summary of the
      // thinking rather than the thinking — and the web shows every
      // segment whole.
      return quote(text);
    }
    if (entry.kind === "tool_start") {
      const desc = toolSemanticDescription(entry.toolName, entry.toolArgs);
      return desc ? `🔧 \`${entry.toolName}\` → ${desc}` : `🔧 \`${entry.toolName}\``;
    }
    const icon = entry.success ? "✅" : "❌";
    return `${icon} \`${entry.toolName}\` · ${toolResultSummary(entry.toolName, entry.result, entry.success)}`;
  }

  /**
   * The block as it should appear right now, or "" when there is nothing
   * to show yet.
   *
   * `done: true` is the finished render, for the caller that keeps the
   * block up after the turn ends (`BOT_KEEP_THINKING`).
   *
   * Append-only, per the file docstring: lines accumulate in order until
   * the budget is gone, and the first line that does not fit is where the
   * block stops. Growing text therefore only ever *extends* this string,
   * never rewrites an earlier part of it — which is what makes it safe to
   * spread across sealed messages.
   */
  render({ done = false } = {}) {
    if (this.entries.length === 0) return "";

    const header = done ? HEADER_DONE : HEADER_LIVE;
    const lines = [];
    let used = header.length;

    for (const entry of this.entries) {
      const line = this._line(entry);
      if (!line) continue;

      if (used + line.length + 1 > MAX_BLOCK_CHARS) {
        // Room for a partial line is worth using — a thought cut short
        // still says what the model was doing; a bare "…" does not.
        const room = MAX_BLOCK_CHARS - used - 2;
        lines.push(room > 80 ? `${line.slice(0, room)}…` : "…");
        break;
      }
      lines.push(line);
      used += line.length + 1;
    }

    if (lines.length === 0) return "";
    return [header, ...lines].join("\n");
  }
}

module.exports = { ThinkingTimeline, toolSemanticDescription, toolResultSummary };
