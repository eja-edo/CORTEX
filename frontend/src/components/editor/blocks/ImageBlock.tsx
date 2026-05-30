import { useRef, useEffect, useCallback, useMemo } from 'react'
import type { BlockNode } from '../../../types/editor'
import { useEditorStore } from '../../../stores/editorStore'

interface ImageBlockProps {
  block: BlockNode
}

export function ImageBlock({ block }: ImageBlockProps) {
  const ref = useRef<HTMLDivElement>(null)
  const updateBlockContent = useEditorStore(s => s.updateBlockContent)
  const setFocusedBlock = useEditorStore(s => s.setFocusedBlock)
  const focusedBlockId = useEditorStore(s => s.focusedBlockId)
  const isFocused = focusedBlockId === block.id

  const parsed = useMemo(() => {
    const match = block.content.match(/!\[(.*?)\]\((.*?)\)/)
    return match
      ? { alt: match[1] || '', src: match[2] || '' }
      : { alt: '', src: block.meta?.language || '' }
  }, [block.content, block.meta?.language])

  useEffect(() => {
    if (ref.current && ref.current.textContent !== block.content) {
      ref.current.textContent = block.content
    }
  }, [block.content])

  const handleInput = useCallback((e: React.FormEvent<HTMLDivElement>) => {
    const text = (e.target as HTMLDivElement).textContent ?? ''
    updateBlockContent(block.id, text)
  }, [block.id, updateBlockContent])

  return (
    <div className="block-image">
      {parsed.src ? (
        <img
          src={parsed.src}
          alt={parsed.alt}
          className="block-image-img"
          loading="lazy"
          onError={e => {
            (e.target as HTMLImageElement).style.display = 'none'
            const parent = (e.target as HTMLImageElement).parentElement
            if (parent) {
              parent.innerHTML = `<span class="block-image-error">Failed to load image</span>`
            }
          }}
        />
      ) : null}
      {parsed.alt && <div className="block-image-caption">{parsed.alt}</div>}
      <div
        ref={ref}
        className={`block-editable block-image-source ${isFocused ? 'block-editable--focused' : ''}`}
        contentEditable="plaintext-only"
        suppressContentEditableWarning
        onInput={handleInput}
        onFocus={() => setFocusedBlock(block.id)}
        onBlur={() => setFocusedBlock(null)}
        data-placeholder="![alt](url)"
      />
    </div>
  )
}
