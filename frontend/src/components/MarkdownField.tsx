import { useRef, useState, useCallback, useEffect } from 'react'
import { renderMarkdownToSanitizedHtml, toggleTaskInMarkdown } from '../utils/markdown/renderToHtml'

interface MarkdownFieldProps {
  value: string
  onChange: (value: string) => void
  /** Fired after the user finishes editing (blur or Esc). Use to commit. */
  onBlur?: () => void
  /**
   * Fired on checkbox click in the rendered preview. Distinct from
   * `onChange` (which is also called) so the parent can decide whether to
   * persist immediately (e.g. PUT) versus wait for blur.
   */
  onImmediateChange?: (newValue: string) => void
  placeholder?: string
  rows?: number
  className?: string
  ariaLabel?: string
}

/**
 * Two-mode field:
 *
 * - **View**: renders the value as sanitized HTML. Clicking a task-list
 *   checkbox toggles the corresponding item and propagates the new value
 *   to the parent (immediate). Double-clicking anywhere else opens edit
 *   mode.
 * - **Edit**: plain `<textarea>` showing the raw markdown source.
 *
 * Empty values render a placeholder line so the field stays discoverable.
 */
export function MarkdownField({
  value,
  onChange,
  onBlur,
  onImmediateChange,
  placeholder,
  rows = 2,
  className,
  ariaLabel,
}: MarkdownFieldProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const previewRef = useRef<HTMLDivElement>(null)
  const [focused, setFocused] = useState(false)

  // When the user enters edit mode, focus the textarea and place the
  // cursor at the end.
  useEffect(() => {
    if (focused) {
      const el = textareaRef.current
      if (el) {
        el.focus()
        const len = el.value.length
        try {
          el.setSelectionRange(len, len)
        } catch {
          /* ignore — setSelectionRange can fail on some input types */
        }
      }
    }
  }, [focused])

  const beginEdit = useCallback(() => {
    setFocused(true)
  }, [])

  const handleTextareaBlur = useCallback(() => {
    setFocused(false)
    onBlur?.()
  }, [onBlur])

  // Event delegation: clicks on a task-list checkbox in the preview toggle
  // the corresponding item without entering edit mode.
  const handlePreviewClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const target = e.target as HTMLElement
      const checkbox = target.closest<HTMLElement>('.block-task-checkbox.md-task-toggle')
      if (!checkbox) return
      e.preventDefault()
      e.stopPropagation()
      const idxAttr = checkbox.getAttribute('data-task-index')
      if (idxAttr == null) return
      const idx = Number(idxAttr)
      if (Number.isNaN(idx)) return
      const next = toggleTaskInMarkdown(value, idx)
      if (next !== value) {
        onChange(next)
        onImmediateChange?.(next)
      }
    },
    [value, onChange, onImmediateChange],
  )

  if (focused) {
    return (
      <textarea
        ref={textareaRef}
        className={`markdown-field-textarea ${className ?? ''}`.trim()}
        rows={rows}
        value={value}
        onChange={e => onChange(e.target.value)}
        onBlur={handleTextareaBlur}
        onKeyDown={e => {
          if (e.key === 'Escape') {
            e.preventDefault()
            ;(e.target as HTMLTextAreaElement).blur()
          }
        }}
        placeholder={placeholder}
        aria-label={ariaLabel}
      />
    )
  }

  const isEmpty = !value.trim()
  const renderedHtml = isEmpty ? '' : renderMarkdownToSanitizedHtml(value, { interactiveTasks: true })

  return (
    <div
      ref={previewRef}
      className={`markdown-field-preview ${isEmpty ? 'is-empty' : ''} ${
        className ?? ''
      }`.trim()}
      onDoubleClick={beginEdit}
      onClick={handlePreviewClick}
    >
      {isEmpty ? (
        <span className="markdown-field-placeholder">{placeholder}</span>
      ) : (
        // eslint-disable-next-line react/no-danger
        <div dangerouslySetInnerHTML={{ __html: renderedHtml }} />
      )}
    </div>
  )
}
