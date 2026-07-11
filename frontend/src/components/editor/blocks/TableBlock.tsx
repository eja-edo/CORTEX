import { useRef, useEffect, useCallback, useMemo } from 'react'
import type { BlockNode } from '../../../types/editor'
import { useEditorStore } from '../../../stores/editorStore'

interface TableBlockProps {
  block: BlockNode
}

function parseTable(md: string): string[][] {
  const lines = md.split('\n').filter(l => l.trim() && !l.trim().match(/^[-| ]+$/))
  return lines.map(line =>
    line
      .split('|')
      .map(c => c.trim())
      .filter((_, i, arr) => i > 0 || arr.length > 1)
      .filter((_, i, arr) => i < arr.length - 1),
  )
}

export function TableBlock({ block }: TableBlockProps) {
  const ref = useRef<HTMLDivElement>(null)
  const updateBlockContent = useEditorStore(s => s.updateBlockContent)
  const setFocusedBlock = useEditorStore(s => s.setFocusedBlock)
  const focusedBlockId = useEditorStore(s => s.focusedBlockId)
  const isFocused = focusedBlockId === block.id

  const data = useMemo(() => {
    try { return parseTable(block.content) } catch { return [] }
  }, [block.content])

  useEffect(() => {
    if (ref.current && ref.current.textContent !== block.content) {
      ref.current.textContent = block.content
    }
  }, [block.content])

  const handleInput = useCallback((e: React.FormEvent<HTMLDivElement>) => {
    const text = (e.target as HTMLDivElement).textContent ?? ''
    updateBlockContent(block.id, text)
  }, [block.id, updateBlockContent])

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    e.preventDefault()
    const text = e.clipboardData.getData('text/plain')
    document.execCommand('insertText', false, text)
  }, [])

  if (data.length === 0) {
    return (
      <div
        ref={ref}
        className={`block-editable block-table-empty ${isFocused ? 'block-editable--focused' : ''}`}
        contentEditable="plaintext-only"
        suppressContentEditableWarning
        onInput={handleInput}
        onFocus={() => setFocusedBlock(block.id)}
        onBlur={() => setFocusedBlock(null)}
        onPaste={handlePaste}
        data-placeholder="| col1 | col2 |"
      />
    )
  }

  const [header, ...rows] = data

  return (
    <div className="block-table">
      <table>
        {header && (
          <thead>
            <tr>
              {header.map((cell, ci) => (
                <th key={ci}>{cell}</th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td key={ci}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div
        ref={ref}
        className={`block-editable block-table-source ${isFocused ? 'block-editable--focused' : ''}`}
        contentEditable="plaintext-only"
        suppressContentEditableWarning
        onInput={handleInput}
        onFocus={() => setFocusedBlock(block.id)}
        onBlur={() => setFocusedBlock(null)}
        onPaste={handlePaste}
        data-placeholder="| col1 | col2 |"
      />
    </div>
  )
}
