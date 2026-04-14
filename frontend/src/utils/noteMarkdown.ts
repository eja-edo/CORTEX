// ============================================================
//  noteMarkdown.ts  —  Markdown ↔ HTML helpers for note editor
// ============================================================

// ─── Helpers ────────────────────────────────────────────────

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}


// ─── plainTextFromMarkdown ───────────────────────────────────

export function plainTextFromMarkdown(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, '') // strip code blocks
    .replace(/\$\$[\s\S]*?\$\$/g, '') // strip math blocks
    .replace(/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/g, '$1')
    .replace(/^[-*]\s+/gm, '')
    .replace(/^\d+\.\s+/gm, '')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^>\s?/gm, '')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/__(.+?)__/g, '$1')
    .replace(/~~(.+?)~~/g, '$1')
    .replace(/\$([^$\n]+)\$/g, '$1')
    .replace(/\n{2,}/g, '\n')
    .trim()
}

// ─── Editor context detection ────────────────────────────────

/**
 * Context of the cursor in the contentEditable editor.
 * Used to decide whether Enter should trigger markdown shortcuts.
 */
export const EditorContext = {
  NORMAL: 'NORMAL',
  CODE_BLOCK: 'CODE_BLOCK',     // inside <pre><code> or unclosed ``` fence
  MATH_BLOCK: 'MATH_BLOCK',     // inside .math-block or unclosed $$ fence
  MATH_INLINE: 'MATH_INLINE',   // inside $...$ (odd number of $ in line)
  LIST_ITEM: 'LIST_ITEM',       // inside <li>
  BLOCKQUOTE: 'BLOCKQUOTE',     // inside <blockquote>
} as const

export type EditorContext = (typeof EditorContext)[keyof typeof EditorContext]

function walkUpForContext(root: HTMLElement, node: Node | null): EditorContext | null {
  let cur: Node | null = node
  while (cur && cur !== root) {
    if (cur instanceof HTMLElement) {
      const tag = cur.tagName.toLowerCase()
      if (tag === 'pre' || tag === 'code') return EditorContext.CODE_BLOCK
      if (tag === 'blockquote') return EditorContext.BLOCKQUOTE
      if (tag === 'li') return EditorContext.LIST_ITEM
      if (cur.classList.contains('math-block')) return EditorContext.MATH_BLOCK
      if (cur.classList.contains('math-inline')) return EditorContext.MATH_INLINE
    }
    cur = cur.parentNode
  }
  return null
}

function detectTextContext(rawText: string): EditorContext | null {
  const text = rawText.replace(/\u00a0/g, ' ')

  // Unclosed fenced code block on this line
  if (/^```/.test(text.trim())) return EditorContext.CODE_BLOCK

  // Unclosed display math block
  if (text.trim() === '$$') return EditorContext.MATH_BLOCK

  // Inline math: odd number of unescaped $ → we're inside one
  const dollarMatches = text.match(/(?<!\\)\$/g) ?? []
  if (dollarMatches.length % 2 !== 0) return EditorContext.MATH_INLINE

  return null
}

// ─── DOM helpers ────────────────────────────────────────────

function closestBlock(root: HTMLElement, node: Node | null): HTMLElement | null {
  let current: Node | null = node
  while (current && current !== root) {
    if (current instanceof HTMLElement && /^(P|DIV|LI|BLOCKQUOTE|PRE)$/i.test(current.tagName)) {
      return current
    }
    current = current.parentNode
  }
  return root.firstElementChild instanceof HTMLElement ? root.firstElementChild : null
}

function placeCaretAtStart(el: HTMLElement): void {
  const selection = window.getSelection()
  if (!selection) return
  const range = document.createRange()
  range.selectNodeContents(el)
  range.collapse(true)
  selection.removeAllRanges()
  selection.addRange(range)
}

function placeCaretAtEnd(el: HTMLElement): void {
  const selection = window.getSelection()
  if (!selection) return
  const range = document.createRange()
  range.selectNodeContents(el)
  range.collapse(false)
  selection.removeAllRanges()
  selection.addRange(range)
}

function insertParagraphAfter(reference: HTMLElement): HTMLElement {
  const paragraph = document.createElement('p')
  paragraph.innerHTML = '<br>'
  reference.parentNode?.insertBefore(paragraph, reference.nextSibling)
  return paragraph
}

function normalizeRootToParagraph(root: HTMLElement): HTMLElement | null {
  const raw = (root.textContent ?? '').replace(/\u00a0/g, ' ')
  const trimmed = raw.trim()
  if (!trimmed) return null

  const p = document.createElement('p')
  p.textContent = trimmed
  root.innerHTML = ''
  root.appendChild(p)
  placeCaretAtEnd(p)
  return p
}

// ─── Code block Enter handling ──────────────────────────────

/**
 * Insert a literal newline inside <pre><code> without leaving the block.
 */
function insertNewlineInCodeBlock(pre: HTMLElement): boolean {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0) return false
  const range = selection.getRangeAt(0)
  if (!range.collapsed) range.deleteContents()

  // Prefer native line break insertion to keep caret behavior consistent.
  if (document.execCommand('insertLineBreak')) {
    pre.scrollTop = pre.scrollHeight
    return true
  }

  const textNode = document.createTextNode('\n')
  range.insertNode(textNode)
  range.setStart(textNode, textNode.length)
  range.collapse(true)
  selection.removeAllRanges()
  selection.addRange(range)
  // Scroll pre into view if needed
  pre.scrollTop = pre.scrollHeight
  return true
}

function findCodeBlockElements(root: HTMLElement, node: Node | null): { pre: HTMLElement; code: HTMLElement } | null {
  let cur: Node | null = node
  let pre: HTMLElement | null = null
  let code: HTMLElement | null = null

  while (cur && cur !== root) {
    if (cur instanceof HTMLElement) {
      const tag = cur.tagName
      if (tag === 'PRE' && !pre) pre = cur
      if (tag === 'CODE' && !code) code = cur
    }
    cur = cur.parentNode
  }

  if (!pre) return null
  if (!code) {
    const nestedCode = pre.querySelector('code')
    if (nestedCode instanceof HTMLElement) code = nestedCode
  }
  if (!code) return null
  return { pre, code }
}

export function applyShiftEnterInCodeBlock(root: HTMLElement): boolean {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0) return false
  const range = selection.getRangeAt(0)
  if (!range.collapsed) return false

  const elements = findCodeBlockElements(root, range.startContainer)
  if (!elements) return false

  const p = document.createElement('p')
  p.innerHTML = '<br>'
  elements.pre.parentNode?.insertBefore(p, elements.pre.nextSibling)
  placeCaretAtStart(p)
  return true
}

// ─── Exit-list-on-empty-li ──────────────────────────────────

function exitListOnEmptyLi(li: HTMLElement): boolean {
  const text = (li.textContent ?? '').replace(/\u00a0/g, ' ').trim()
  if (text !== '') return false

  const list = li.parentElement // <ul> or <ol>
  if (!list) return false

  // Remove the empty li
  list.removeChild(li)

  // Insert <p> after the list
  const p = document.createElement('p')
  p.innerHTML = '<br>'
  list.parentNode?.insertBefore(p, list.nextSibling)
  placeCaretAtStart(p)
  return true
}

// ─── Blockquote continue / exit ─────────────────────────────

/**
 * Inside a blockquote:
 *   - Empty line → exit blockquote, insert <p> after
 *   - Otherwise → continue (browser default adds new <p> inside bq, which is fine)
 *     We return false to let the browser handle it.
 */
function handleEnterInBlockquote(bq: HTMLElement, block: HTMLElement): boolean {
  const text = (block.textContent ?? '').replace(/\u00a0/g, ' ').trim()
  if (text !== '') return false // let browser insert next <p> in blockquote

  // Empty line → exit
  const p = document.createElement('p')
  p.innerHTML = '<br>'
  bq.parentNode?.insertBefore(p, bq.nextSibling)
  placeCaretAtStart(p)
  return true
}

// ─── Main export ─────────────────────────────────────────────

/**
 * Call this in the `onKeyDown` handler when `e.key === 'Enter'`.
 *
 * Returns `true` if the event was handled (caller should `e.preventDefault()`).
 * Returns `false` to let the browser handle it normally.
 */
export function applyMarkdownShortcutOnEnter(root: HTMLElement): boolean {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0) return false

  const range = selection.getRangeAt(0)
  if (!range.collapsed) return false

  // ── 1. Check DOM ancestry for structural context
  const domCtx = walkUpForContext(root, range.startContainer)

  if (domCtx === EditorContext.CODE_BLOCK) {
    // Find the <pre> ancestor to auto-scroll it
    let pre: Node | null = range.startContainer
    while (pre && !(pre instanceof HTMLElement && pre.tagName === 'PRE')) pre = pre.parentNode
    insertNewlineInCodeBlock((pre as HTMLElement) ?? root)
    return true
  }

  if (domCtx === EditorContext.MATH_BLOCK || domCtx === EditorContext.MATH_INLINE) {
    // Let browser insert newline; math blocks are not transformed
    return false
  }

  if (domCtx === EditorContext.LIST_ITEM) {
    const li = (() => {
      let cur: Node | null = range.startContainer
      while (cur && !(cur instanceof HTMLElement && cur.tagName === 'LI')) cur = cur.parentNode
      return cur as HTMLElement | null
    })()
    if (li && exitListOnEmptyLi(li)) return true
    return false // let browser continue the list
  }

  if (domCtx === EditorContext.BLOCKQUOTE) {
    const bq = (() => {
      let cur: Node | null = range.startContainer
      while (cur && !(cur instanceof HTMLElement && cur.tagName === 'BLOCKQUOTE')) cur = cur.parentNode
      return cur as HTMLElement | null
    })()
    const block = closestBlock(root, range.startContainer)
    if (bq && block) return handleEnterInBlockquote(bq, block)
    return false
  }

  // ── 2. Check text content of current block for inline/fence context
  let block = closestBlock(root, range.startContainer)
  if (!block) {
    block = normalizeRootToParagraph(root)
  }
  if (!block) return false

  const raw = (block.textContent ?? '').replace(/\u00a0/g, ' ')
  const textCtx = detectTextContext(raw)

  if (textCtx === EditorContext.CODE_BLOCK) {
    // User just typed ``` on a line and pressed Enter → open a code block in the DOM
    const lang = raw.trim().slice(3).trim()
    const pre = document.createElement('pre')
    const code = document.createElement('code')
    if (lang) code.className = `language-${lang}`
    code.textContent = ''
    pre.appendChild(code)
    block.replaceWith(pre)

    // Place caret at start of empty code block
    const r = document.createRange()
    r.selectNodeContents(code)
    r.collapse(true)
    selection.removeAllRanges()
    selection.addRange(r)
    return true
  }

  if (textCtx === EditorContext.MATH_INLINE) {
    // Odd number of $ → user is typing an inline formula, do not transform
    return false
  }

  if (textCtx === EditorContext.MATH_BLOCK) {
    // User typed $$ on a line → open a math block div
    const div = document.createElement('div')
    div.className = 'math-block'
    div.textContent = '$$\n\n$$'
    block.replaceWith(div)
    // Place caret at inner position (between the $$)
    const inner = div.firstChild as Text | null
    if (inner) {
      const r = document.createRange()
      r.setStart(inner, 3) // after first "$$\n"
      r.collapse(true)
      selection.removeAllRanges()
      selection.addRange(r)
    }
    return true
  }

  // ── 3. Normal markdown shortcut transforms (existing logic + blockquote)
  const text = raw.trim()
  if (!text) return false

  // Checkbox list: - [ ] text
  if (/^-\s+\[\s\]\s+/.test(text)) {
    const itemText = text.replace(/^-\s+\[\s\]\s+/, '')
    const ul = document.createElement('ul')
    const li = document.createElement('li')
    li.innerHTML = `&#x2610; ${escapeHtml(itemText)}`
    const nextLi = document.createElement('li')
    nextLi.innerHTML = '<br>'
    ul.append(li, nextLi)
    block.replaceWith(ul)
    placeCaretAtStart(nextLi)
    return true
  }

  // Unordered list: - or * prefix
  if (/^[-*]\s+/.test(text)) {
    const itemText = text.replace(/^[-*]\s+/, '')
    const ul = document.createElement('ul')
    const li = document.createElement('li')
    li.innerHTML = escapeHtml(itemText)
    const nextLi = document.createElement('li')
    nextLi.innerHTML = '<br>'
    ul.append(li, nextLi)
    block.replaceWith(ul)
    placeCaretAtStart(nextLi)
    return true
  }

  // Ordered list: 1. prefix
  if (/^\d+\.\s+/.test(text)) {
    const itemText = text.replace(/^\d+\.\s+/, '')
    const ol = document.createElement('ol')
    const li = document.createElement('li')
    li.innerHTML = escapeHtml(itemText)
    const nextLi = document.createElement('li')
    nextLi.innerHTML = '<br>'
    ol.append(li, nextLi)
    block.replaceWith(ol)
    placeCaretAtStart(nextLi)
    return true
  }

  // Blockquote: > prefix
  if (/^>\s?/.test(text)) {
    const itemText = text.replace(/^>\s?/, '')
    const bq = document.createElement('blockquote')
    const p1 = document.createElement('p')
    p1.innerHTML = escapeHtml(itemText)
    const p2 = document.createElement('p')
    p2.innerHTML = '<br>'
    bq.append(p1, p2)
    block.replaceWith(bq)
    placeCaretAtStart(p2)
    return true
  }

  // Heading H1: # prefix
  if (/^#\s+/.test(text) && !text.startsWith('##')) {
    const content = text.replace(/^#\s+/, '')
    block.innerHTML = `<strong>${escapeHtml(content)}</strong>`
    const next = insertParagraphAfter(block)
    placeCaretAtStart(next)
    return true
  }

  // Heading H2: ## prefix
  if (/^##\s+/.test(text)) {
    const content = text.replace(/^##\s+/, '')
    block.innerHTML = `<u>${escapeHtml(content)}</u>`
    const next = insertParagraphAfter(block)
    placeCaretAtStart(next)
    return true
  }

  // Horizontal rule: --- or *** or ___
  if (/^(---|\*\*\*|___)$/.test(text)) {
    const hr = document.createElement('hr')
    const next = document.createElement('p')
    next.innerHTML = '<br>'
    block.replaceWith(hr)
    hr.parentNode?.insertBefore(next, hr.nextSibling)
    placeCaretAtStart(next)
    return true
  }

  return false
}

// ─── Tab key handler (indent in code blocks) ─────────────────

/**
 * Call this in `onKeyDown` when `e.key === 'Tab'`.
 * Inserts 2 spaces inside code blocks instead of tabbing focus away.
 * Returns true if handled.
 */
export function applyTabInCodeBlock(root: HTMLElement): boolean {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0) return false
  const range = selection.getRangeAt(0)

  const domCtx = walkUpForContext(root, range.startContainer)
  if (domCtx !== EditorContext.CODE_BLOCK) return false

  if (!range.collapsed) range.deleteContents()
  const spaces = document.createTextNode('  ')
  range.insertNode(spaces)
  range.setStartAfter(spaces)
  range.collapse(true)
  selection.removeAllRanges()
  selection.addRange(range)
  return true
}

// Re-export so callers don't need to change imports
export { placeCaretAtEnd }