import { useRef, useEffect, useCallback, useMemo, useContext } from 'react'
import type { BlockNode } from '../../../types/editor'
import { useEditorStore } from '../../../stores/editorStore'
import { ReadOnlyCtx } from '../EditorSurface'

interface TableBlockProps {
  block: BlockNode
}

function parseTable(md: string): string[][] {
  const lines = md.split('\n').filter(l => l.trim() && !l.trim().match(/^[-| ]+$/))
  return lines.map(line => {
    const cells = line.split('|').map(c => c.trim())
    if (cells.length > 0 && cells[0] === '') cells.shift()
    if (cells.length > 0 && cells[cells.length - 1] === '') cells.pop()
    return cells
  })
}

export function TableBlock({ block }: TableBlockProps) {
  const ref = useRef<HTMLDivElement>(null)
  const readOnly = useContext(ReadOnlyCtx)
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
    if (readOnly) return
    const text = (e.target as HTMLDivElement).textContent ?? ''
    updateBlockContent(block.id, text)
  }, [block.id, updateBlockContent, readOnly])

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    if (readOnly) return
    e.preventDefault()
    const text = e.clipboardData.getData('text/plain')
    document.execCommand('insertText', false, text)
  }, [readOnly])

  if (data.length === 0) {
    return (
      <div
        ref={ref}
        className={`block-editable block-table-empty ${isFocused ? 'block-editable--focused' : ''}`}
        contentEditable={readOnly ? "false" : "plaintext-only"}
        suppressContentEditableWarning
        onInput={handleInput}
        onFocus={() => { if (!readOnly) setFocusedBlock(block.id) }}
        onBlur={() => { if (!readOnly) setFocusedBlock(null) }}
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
      {isFocused && !readOnly && (
        <div
          ref={ref}
          className="block-editable block-table-source block-editable--focused"
          contentEditable="plaintext-only"
          suppressContentEditableWarning
          onInput={handleInput}
          onFocus={() => setFocusedBlock(block.id)}
          onBlur={() => setFocusedBlock(null)}
          onPaste={handlePaste}
          data-placeholder="| col1 | col2 |"
        />
      )}
    </div>
  )
}
