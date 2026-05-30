import { useRef, useEffect, useCallback, useState } from 'react'
import type { BlockNode } from '../../../types/editor'
import { useEditorStore } from '../../../stores/editorStore'

interface CodeBlockProps {
  block: BlockNode
}

export function CodeBlock({ block }: CodeBlockProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [copied, setCopied] = useState(false)
  const language = block.meta?.language ?? ''
  const updateBlockContent = useEditorStore(s => s.updateBlockContent)
  const setFocusedBlock = useEditorStore(s => s.setFocusedBlock)
  const focusedBlockId = useEditorStore(s => s.focusedBlockId)
  const isFocused = focusedBlockId === block.id

  useEffect(() => {
    if (ref.current && ref.current.textContent !== block.content) {
      ref.current.textContent = block.content
    }
  }, [block.content])

  const handleInput = useCallback((e: React.FormEvent<HTMLDivElement>) => {
    const text = (e.target as HTMLDivElement).textContent ?? ''
    updateBlockContent(block.id, text)
  }, [block.id, updateBlockContent])

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(block.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {}
  }, [block.content])

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    e.preventDefault()
    const text = e.clipboardData.getData('text/plain')
    document.execCommand('insertText', false, text)
  }, [])

  return (
    <div className="block-code">
      <div className="block-code-header" contentEditable={false}>
        <span className="block-code-lang">{language || 'code'}</span>
        <button
          type="button"
          className="block-code-copy-btn"
          onClick={handleCopy}
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <div
        ref={ref}
        className={`block-code-editable block-editable ${isFocused ? 'block-editable--focused' : ''}`}
        contentEditable="plaintext-only"
        suppressContentEditableWarning
        onInput={handleInput}
        onFocus={() => setFocusedBlock(block.id)}
        onBlur={() => setFocusedBlock(null)}
        onPaste={handlePaste}
        spellCheck={false}
      />
    </div>
  )
}
