// ── Single source of truth for markdown-it config ────────────────────────────
//
// IMPORTANT: this file is mirrored by `backend/app/services/markdown_config.py`.
// Any change here MUST be applied to the backend module as well so that note
// previews (rendered server-side) match the editor & AI chat output rendered
// in the browser. A regression test in
// `frontend/src/utils/markdown/__tests__/shared-config.spec.ts` enforces the
// shape of this object.
export const MARKDOWN_IT_OPTIONS: {
  html: boolean
  linkify: boolean
  typographer: boolean
  breaks: boolean
} = {
  html: false,
  linkify: true,
  typographer: true,
  breaks: true,
}

// Whitelist used by DOMPurify after `md.render()`. Keep aligned with the
// `_ALLOWED_TAGS` / `_ALLOWED_ATTRIBUTES` in `backend/app/services/notes.py`.
// Frontend allows a couple of extras (mark, sub, sup, span) that the editor
// surfaces through bubble toolbar (highlight, sub/sup future-proofing).
export const SANITIZE_ALLOWED_TAGS: readonly string[] = [
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'p', 'br', 'hr', 'strong', 'em', 's', 'del', 'code', 'pre',
  'ul', 'ol', 'li',
  'blockquote', 'a', 'span', 'mark', 'sub', 'sup', 'img',
]

export const SANITIZE_ALLOWED_ATTR: readonly string[] = [
  'href', 'title', 'class', 'target', 'rel',
  'src', 'alt',
]
