import { useRef, useEffect, useCallback, useMemo, useState, useContext } from 'react'
import type { BlockNode } from '../../../types/editor'
import { useEditorStore } from '../../../stores/editorStore'
import { uploadNoteImage } from '../../../services/api'
import { ReadOnlyCtx } from '../EditorSurface'

interface ImageBlockProps {
  block: BlockNode
}

export function ImageBlock({ block }: ImageBlockProps) {
  const ref = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const readOnly = useContext(ReadOnlyCtx)
  const updateBlockContent = useEditorStore(s => s.updateBlockContent)
  const setFocusedBlock = useEditorStore(s => s.setFocusedBlock)
  const focusedBlockId = useEditorStore(s => s.focusedBlockId)
  const noteId = useEditorStore(s => s.noteId)
  const isFocused = focusedBlockId === block.id
  const [uploading, setUploading] = useState(false)

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

  useEffect(() => {
    if (isFocused && ref.current) {
      ref.current.focus()
      const sel = window.getSelection()
      if (sel) {
        const range = document.createRange()
        range.selectNodeContents(ref.current)
        range.collapse(false)
        sel.removeAllRanges()
        sel.addRange(range)
      }
    }
  }, [isFocused])

  const handleInput = useCallback((e: React.FormEvent<HTMLDivElement>) => {
    if (readOnly) return
    const text = (e.target as HTMLDivElement).textContent ?? ''
    updateBlockContent(block.id, text)
  }, [block.id, updateBlockContent, readOnly])

  const handleUploadClick = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleFileChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !noteId) return

    setUploading(true)
    try {
      const result = await uploadNoteImage(noteId, file)
      const md = `![${file.name}](${result.url})`
      updateBlockContent(block.id, md)
    } catch {
      // upload error handled silently
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }, [noteId, block.id, updateBlockContent])

  const handlePaste = useCallback(async (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items
    if (!items || !noteId) return

    for (const item of Array.from(items)) {
      if (item.type.startsWith('image/')) {
        e.preventDefault()
        const file = item.getAsFile()
        if (!file) continue

        setUploading(true)
        try {
          const result = await uploadNoteImage(noteId, file)
          const md = `![pasted-image](${result.url})`
          updateBlockContent(block.id, md)
        } catch {
          // upload error
        } finally {
          setUploading(false)
        }
        return
      }
    }
  }, [noteId, block.id, updateBlockContent])

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault()
    const file = e.dataTransfer?.files?.[0]
    if (!file?.type.startsWith('image/') || !noteId) return

    setUploading(true)
    try {
      const result = await uploadNoteImage(noteId, file)
      const md = `![${file.name}](${result.url})`
      updateBlockContent(block.id, md)
    } catch {
      // upload error
    } finally {
      setUploading(false)
    }
  }, [noteId, block.id, updateBlockContent])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
  }, [])

  const hasImage = !!parsed.src && !uploading

  return (
    <div
      className="block-image"
      onPaste={handlePaste}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
    >
      {uploading && (
        <div className="block-image-uploading">Uploading…</div>
      )}
      {hasImage ? (
        <>
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
        </>
      ) : !uploading ? (
        <div className="block-image-toolbar-row">
          <div
            ref={ref}
            className={`block-editable block-image-source ${isFocused ? 'block-editable--focused' : ''}`}
            contentEditable={readOnly ? "false" : "plaintext-only"}
            suppressContentEditableWarning
            onInput={handleInput}
            onFocus={() => { if (!readOnly) setFocusedBlock(block.id) }}
            onBlur={() => { if (!readOnly) setFocusedBlock(null) }}
            data-placeholder="![alt](url)"
          />
          {!readOnly && (
            <button
              className="block-image-upload-btn"
              onClick={handleUploadClick}
              disabled={uploading || !noteId}
              title="Upload image"
            >
              📷
            </button>
          )}
        </div>
      ) : null}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={handleFileChange}
      />
    </div>
  )
}
