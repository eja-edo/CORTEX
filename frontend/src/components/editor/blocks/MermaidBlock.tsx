import { useRef, useEffect, useState, useCallback, useContext } from 'react'
import type { BlockNode } from '../../../types/editor'
import { useEditorStore } from '../../../stores/editorStore'
import { ReadOnlyCtx } from '../EditorSurface'

interface MermaidBlockProps {
  block: BlockNode
}

declare global {
  interface Window {
    mermaid?: {
      run: (config: { nodes: Iterable<HTMLElement> }) => Promise<void>
    }
  }
}

export function MermaidBlock({ block }: MermaidBlockProps) {
  const ref = useRef<HTMLDivElement>(null)
  const editorRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const readOnly = useContext(ReadOnlyCtx)
  const updateBlockContent = useEditorStore(s => s.updateBlockContent)
  const setFocusedBlock = useEditorStore(s => s.setFocusedBlock)
  const focusedBlockId = useEditorStore(s => s.focusedBlockId)
  const isFocused = focusedBlockId === block.id

  useEffect(() => {
    if (!ref.current || !block.content) return
    const render = async () => {
      try {
        const { default: mermaid } = await import('mermaid')
        mermaid.initialize({ startOnLoad: false, theme: 'default' })
        const { svg } = await mermaid.render('mermaid-svg-' + block.id, block.content)
        if (ref.current) {
          ref.current.innerHTML = svg
        }
        setError(null)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to render diagram')
      }
    }
    render()
  }, [block.content, block.id])

  useEffect(() => {
    if (editorRef.current && editorRef.current.textContent !== block.content) {
      editorRef.current.textContent = block.content
    }
  }, [block.content])

  useEffect(() => {
    if (!readOnly && isFocused && editorRef.current) {
      editorRef.current.focus()
      const sel = window.getSelection()
      if (sel) {
        const range = document.createRange()
        range.selectNodeContents(editorRef.current)
        range.collapse(false)
        sel.removeAllRanges()
        sel.addRange(range)
      }
    }
  }, [isFocused, readOnly])

  const handleInput = useCallback((e: React.FormEvent<HTMLDivElement>) => {
    if (readOnly) return
    const text = (e.target as HTMLDivElement).textContent ?? ''
    updateBlockContent(block.id, text)
  }, [block.id, updateBlockContent, readOnly])

  return (
    <div className="block-mermaid">
      {error ? (
        <div className="block-mermaid-error">
          <div className="block-mermaid-error-text">{error}</div>
        </div>
      ) : (
        <div ref={ref} className="block-mermaid-svg" />
      )}
      <div
        ref={editorRef}
        className={`block-editable block-mermaid-source ${isFocused ? 'block-editable--focused' : ''}`}
        contentEditable={readOnly ? "false" : "plaintext-only"}
        suppressContentEditableWarning
        onInput={handleInput}
        onFocus={() => { if (!readOnly) setFocusedBlock(block.id) }}
        onBlur={() => { if (!readOnly) setFocusedBlock(null) }}
        data-placeholder="flowchart LR&#10;A --> B"
      />
    </div>
  )
}
