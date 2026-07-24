import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import {
  MARKDOWN_IT_OPTIONS,
  SANITIZE_ALLOWED_TAGS,
  SANITIZE_ALLOWED_ATTR,
} from './config'

// ── Read-only (full) renderer ───────────────────────────────────────────────
//
// Keeps `breaks: true` so bare newlines in markdown produce `<br>` in the
// output. Used by AskAI, ConversationDetail, NoteSidebar.
const md = new MarkdownIt(MARKDOWN_IT_OPTIONS)

// ── Inline (editor) renderer ────────────────────────────────────────────────
//
// Uses `breaks: false` because contentEditable blocks already carry
// `white-space: pre-wrap` (editor.css), making newlines visible as line
// breaks natively. Adding `<br>` on top would create double spacing.
const mdInline = new MarkdownIt({ ...MARKDOWN_IT_OPTIONS, breaks: false })

/**
 * Render markdown source to sanitized HTML. Suitable for read-only views
 * that inject the result via `dangerouslySetInnerHTML`.
 *
 * Behaviour matches the markdownguide.org basic syntax plus the project
 * extensions: GFM task list (NOT in basic), strikethrough (extended), callout
 * (custom — only used as raw HTML, which `html:false` keeps safe anyway).
 *
 * @param interactiveTasks  When true, checkboxes are rendered without the
 *   `disabled` attribute and carry `data-task-index`.  The caller is
 *   responsible for attaching a change listener and calling
 *   {@link toggleTaskInMarkdown} to persist the toggle.
 */
export function renderMarkdownToSanitizedHtml(
  content: string,
  opts?: { interactiveTasks?: boolean },
): string {
  if (!content) return ''
  const raw = md.render(content)
  const withTaskItems = renderTaskListItems(raw, opts?.interactiveTasks)
  return DOMPurify.sanitize(withTaskItems, {
    ALLOWED_TAGS: [...SANITIZE_ALLOWED_TAGS, 'input'],
    ALLOWED_ATTR: opts?.interactiveTasks
      ? [...SANITIZE_ALLOWED_ATTR, 'type', 'checked', 'data-task-index']
      : [...SANITIZE_ALLOWED_ATTR, 'type', 'disabled', 'checked'],
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed'],
  })
}

/**
 * Render an *inline* markdown snippet (no block-level elements such as
 * headings/lists/paragraphs) to sanitized HTML. Used by the rich-text editor
 * to convert the live `block.content` into a contenteditable innerHTML
 * without round-tripping through DOM and regex.
 *
 * Using `md.renderInline` ensures we share the same parser configuration as
 * the read-only paths — no duplicated regex, no drift in behaviour for
 * reference-style links, autolink, escapes, etc.
 *
 * Note: `renderInline` does not emit block-level tokens (paragraphs, headings)
 * or images. For the rare case where the block content is a bare image
 * (`![alt](src)`), we fall back to `md.render()` and strip the surrounding
 * `<p>` wrapper so the editor can still display it.
 */
export function renderInlineMarkdownToHtml(content: string): string {
  if (!content) return ''
  // Detect bare image (with optional title) or linked image — these are not
  // rendered by renderInline.
  const trimmed = content.trim()
  const bareImage = trimmed.match(/^!\[.*?\]\(.*?\)\s*$/)
  const linkedImage = trimmed.match(/^\[!\[.*?\]\(.*?\)\]\(.*?\)\s*$/)
  if (bareImage || linkedImage) {
    const raw = mdInline.render(content).trim()
    // strip outer <p> and </p> wrapper since this is inline rendering
    const unwrapped = raw.replace(/^<p>([\s\S]*?)<\/p>$/, '$1')
    return DOMPurify.sanitize(unwrapped, {
      ALLOWED_TAGS: ['img', 'a'],
      ALLOWED_ATTR: ['href', 'title', 'src', 'alt'],
      FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed'],
    })
  }
  const raw = mdInline.renderInline(content)
  return DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: [
      'strong', 'em', 's', 'del', 'code', 'a', 'br', 'span', 'mark', 'sub', 'sup',
    ],
    ALLOWED_ATTR: ['href', 'title', 'class', 'target', 'rel'],
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed'],
  })
}

// ── Task-list (GFM checkbox) post-processor ──────────────────────────────────
//
// markdown-it does not natively support `- [ ]` / `- [x]` syntax. We convert
// the rendered `<li>[ ]</li>` / `<li>[x]</li>` into checkboxes at the HTML
// level. This is safer and simpler than writing a full markdown-it plugin.
function renderTaskListItems(html: string, interactive?: boolean): string {
  let idx = 0
  return html.replace(
    /<li>(\s*)\[([ xX])\]\s*/g,
    (_, ws, mark) => {
      const checked = mark.toLowerCase() === 'x'
      if (interactive) {
        return `<li class="task-list-item">${ws}<input type="checkbox" data-task-index="${idx++}"${
          checked ? ' checked' : ''
        }> `
      }
      return `<li class="task-list-item">${ws}<input type="checkbox" disabled${
        checked ? ' checked' : ''
      }> `
    },
  )
}

// Exposed for unit tests — do not use directly in feature code.
export const _internal = { md, mdInline }

/**
 * Flip the Nth task-list checkbox in raw markdown between `[ ]` and `[x]`.
 *
 * Counts every occurrence of `[ ]`, `[x]`, `[X]` that appears inside a
 * list-item context (preceded by `- `, `* `, `+ `, or a number `1. ` etc.).
 * Returns the modified markdown with that one item toggled.
 */
export function toggleTaskInMarkdown(markdown: string, taskIndex: number): string {
  let idx = 0
  return markdown.replace(
    /^(\s*(?:[-*+]|\d+\.)\s+)\[([ xX])\]/gm,
    (match, prefix, mark) => {
      if (idx === taskIndex) {
        const toggled = mark === ' ' ? 'x' : ' '
        idx++
        return `${prefix}[${toggled}]`
      }
      idx++
      return match
    },
  )
}

