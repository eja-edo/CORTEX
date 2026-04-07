function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function normalizeInlineMarkdown(text: string): string {
  let out = escapeHtml(text)
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  out = out.replace(/\*(.+?)\*/g, '<em>$1</em>')
  out = out.replace(/~~(.+?)~~/g, '<s>$1</s>')
  out = out.replace(/__(.+?)__/g, '<u>$1</u>')
  out = out.replace(/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
  return out
}

export function markdownToHtml(md: string): string {
  const lines = md.replace(/\r\n/g, '\n').split('\n')
  const html: string[] = []
  let inUl = false
  let inOl = false

  const closeLists = () => {
    if (inUl) {
      html.push('</ul>')
      inUl = false
    }
    if (inOl) {
      html.push('</ol>')
      inOl = false
    }
  }

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) {
      closeLists()
      continue
    }

    const h1 = trimmed.match(/^#\s+(.+)/)
    if (h1) {
      closeLists()
      html.push(`<p><strong>${normalizeInlineMarkdown(h1[1])}</strong></p>`)
      continue
    }
    const h2 = trimmed.match(/^##\s+(.+)/)
    if (h2) {
      closeLists()
      html.push(`<p><u>${normalizeInlineMarkdown(h2[1])}</u></p>`)
      continue
    }

    const ul = trimmed.match(/^[-*]\s+(.+)/)
    if (ul) {
      if (!inUl) {
        closeLists()
        html.push('<ul>')
        inUl = true
      }
      html.push(`<li>${normalizeInlineMarkdown(ul[1])}</li>`)
      continue
    }

    const ol = trimmed.match(/^\d+\.\s+(.+)/)
    if (ol) {
      if (!inOl) {
        closeLists()
        html.push('<ol>')
        inOl = true
      }
      html.push(`<li>${normalizeInlineMarkdown(ol[1])}</li>`)
      continue
    }

    closeLists()
    html.push(`<p>${normalizeInlineMarkdown(trimmed)}</p>`)
  }

  closeLists()
  return html.join('')
}

export function htmlToMarkdown(html: string): string {
  if (!html.trim()) return ''
  if (typeof document === 'undefined') {
    return html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
  }

  const root = document.createElement('div')
  root.innerHTML = html

  const inlineToMarkdown = (el: Element): string => {
    const walk = (node: Node): string => {
      if (node.nodeType === Node.TEXT_NODE) return (node.textContent ?? '').replace(/\u00a0/g, ' ')
      if (!(node instanceof HTMLElement)) return ''
      const content = Array.from(node.childNodes).map(walk).join('')
      switch (node.tagName.toLowerCase()) {
        case 'strong':
        case 'b':
          return `**${content}**`
        case 'em':
        case 'i':
          return `*${content}*`
        case 'u':
          return `__${content}__`
        case 's':
        case 'strike':
          return `~~${content}~~`
        case 'a': {
          const href = node.getAttribute('href') ?? ''
          return href ? `[${content}](${href})` : content
        }
        case 'br':
          return '\n'
        default:
          return content
      }
    }
    return Array.from(el.childNodes).map(walk).join('').replace(/\s+/g, ' ').trim()
  }

  const lines: string[] = []
  for (const child of Array.from(root.children)) {
    const tag = child.tagName.toLowerCase()
    if (tag === 'ul') {
      for (const li of Array.from(child.children)) {
        lines.push(`- ${inlineToMarkdown(li)}`)
      }
      continue
    }
    if (tag === 'ol') {
      let i = 1
      for (const li of Array.from(child.children)) {
        lines.push(`${i}. ${inlineToMarkdown(li)}`)
        i += 1
      }
      continue
    }
    if (tag === 'p' || tag === 'div') {
      const text = inlineToMarkdown(child)
      if (text) lines.push(text)
      continue
    }
    const text = inlineToMarkdown(child)
    if (text) lines.push(text)
  }
  return lines.join('\n').trim()
}

export function plainTextFromMarkdown(md: string): string {
  return md
    .replace(/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/g, '$1')
    .replace(/^[-*]\s+/gm, '')
    .replace(/^\d+\.\s+/gm, '')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/__(.+?)__/g, '$1')
    .replace(/~~(.+?)~~/g, '$1')
    .replace(/\n{2,}/g, '\n')
    .trim()
}

function closestBlock(root: HTMLElement, node: Node | null): HTMLElement | null {
  let current: Node | null = node
  while (current && current !== root) {
    if (current instanceof HTMLElement && /^(P|DIV|LI)$/i.test(current.tagName)) {
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

function insertParagraphAfter(reference: HTMLElement): HTMLElement {
  const paragraph = document.createElement('p')
  paragraph.innerHTML = '<br>'
  reference.parentNode?.insertBefore(paragraph, reference.nextSibling)
  return paragraph
}

export function applyMarkdownShortcutOnEnter(root: HTMLElement): boolean {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0) return false

  const range = selection.getRangeAt(0)
  if (!range.collapsed) return false

  const block = closestBlock(root, range.startContainer)
  if (!block) return false

  const raw = (block.textContent ?? '').replace(/\u00a0/g, ' ')
  const text = raw.trim()
  if (!text) return false

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

  if (/^#{1,2}\s+/.test(text)) {
    const level = text.startsWith('##') ? 2 : 1
    const content = text.replace(/^#{1,2}\s+/, '')
    block.innerHTML = level === 1 ? `<strong>${escapeHtml(content)}</strong>` : `<u>${escapeHtml(content)}</u>`
    const next = insertParagraphAfter(block)
    placeCaretAtStart(next)
    return true
  }

  return false
}
