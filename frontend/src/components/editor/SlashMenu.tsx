import { useEffect, useRef, useCallback, useMemo, useState } from 'react'
import { useEditorStore } from '../../stores/editorStore'
import {
  Type, Heading1, Heading2, Heading3, List, ListOrdered,
  CheckSquare, Quote, Code, Table, Info, ChevronRight,
  Image, Minus, Workflow,
} from 'lucide-react'
import type { BlockNode } from '../../types/editor'

interface SlashItem {
  type: BlockNode['type']
  label: string
  icon: React.ReactNode
  searchTerms: string[]
  category: string
}

const SLASH_ITEMS: SlashItem[] = [
  { type: 'paragraph', label: 'Text', icon: <Type size={16} />, searchTerms: ['text', 'plain', 'paragraph'], category: 'Basic' },
  { type: 'heading_1', label: 'Heading 1', icon: <Heading1 size={16} />, searchTerms: ['h1', 'heading 1', 'title'], category: 'Basic' },
  { type: 'heading_2', label: 'Heading 2', icon: <Heading2 size={16} />, searchTerms: ['h2', 'heading 2', 'subtitle'], category: 'Basic' },
  { type: 'heading_3', label: 'Heading 3', icon: <Heading3 size={16} />, searchTerms: ['h3', 'heading 3'], category: 'Basic' },
  { type: 'bullet_list', label: 'Bullet list', icon: <List size={16} />, searchTerms: ['bullet', 'list', 'ul'], category: 'Lists' },
  { type: 'ordered_list', label: 'Numbered list', icon: <ListOrdered size={16} />, searchTerms: ['ordered', 'numbered', 'ol'], category: 'Lists' },
  { type: 'task_list', label: 'To-do list', icon: <CheckSquare size={16} />, searchTerms: ['todo', 'task', 'checklist'], category: 'Lists' },
  { type: 'blockquote', label: 'Blockquote', icon: <Quote size={16} />, searchTerms: ['quote', 'blockquote', 'citation'], category: 'Blocks' },
  { type: 'code_block', label: 'Code', icon: <Code size={16} />, searchTerms: ['code', 'pre', 'fence'], category: 'Blocks' },
  { type: 'table', label: 'Table', icon: <Table size={16} />, searchTerms: ['table', 'grid', 'csv'], category: 'Blocks' },
  { type: 'divider', label: 'Divider', icon: <Minus size={16} />, searchTerms: ['divider', 'hr', 'separator', 'line'], category: 'Blocks' },
  { type: 'callout', label: 'Callout', icon: <Info size={16} />, searchTerms: ['callout', 'info', 'note', 'tip', 'warning'], category: 'Blocks' },
  { type: 'toggle', label: 'Toggle', icon: <ChevronRight size={16} />, searchTerms: ['toggle', 'collapse', 'details'], category: 'Blocks' },
  { type: 'image', label: 'Image', icon: <Image size={16} />, searchTerms: ['image', 'img', 'picture', 'photo'], category: 'Media' },
  { type: 'mermaid', label: 'Mermaid', icon: <Workflow size={16} />, searchTerms: ['mermaid', 'diagram', 'flowchart'], category: 'Media' },
]

export function SlashMenu() {
  const slashMenu = useEditorStore(s => s.slashMenu)
  const closeSlashMenu = useEditorStore(s => s.closeSlashMenu)
  const setSlashMenuSearch = useEditorStore(s => s.setSlashMenuSearch)
  const insertBlockAfter = useEditorStore(s => s.insertBlockAfter)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (slashMenu.open) {
      setSelectedIndex(0)
      setSlashMenuSearch('')
    }
  }, [slashMenu.open, setSlashMenuSearch])

  const filtered = useMemo(() => {
    if (!slashMenu.search) return SLASH_ITEMS
    const q = slashMenu.search.toLowerCase()
    return SLASH_ITEMS.filter(
      item =>
        item.label.toLowerCase().includes(q) ||
        item.searchTerms.some(t => t.includes(q)),
    )
  }, [slashMenu.search])

  const handleSelect = useCallback((item: SlashItem) => {
    if (slashMenu.anchorBlockId) {
      insertBlockAfter(slashMenu.anchorBlockId, item.type)
    }
    closeSlashMenu()
  }, [slashMenu.anchorBlockId, insertBlockAfter, closeSlashMenu])

  useEffect(() => {
    if (!slashMenu.open) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (!slashMenu.open) return

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault()
          setSelectedIndex(prev => Math.min(prev + 1, filtered.length - 1))
          break
        case 'ArrowUp':
          e.preventDefault()
          setSelectedIndex(prev => Math.max(prev - 1, 0))
          break
        case 'Enter':
          e.preventDefault()
          if (filtered[selectedIndex]) {
            handleSelect(filtered[selectedIndex])
          }
          break
        case 'Escape':
          e.preventDefault()
          closeSlashMenu()
          break
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [slashMenu.open, filtered, selectedIndex, handleSelect, closeSlashMenu])

  useEffect(() => {
    if (!slashMenu.open) return

    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        closeSlashMenu()
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [slashMenu.open, closeSlashMenu])

  if (!slashMenu.open) return null

  const grouped = filtered.reduce<Record<string, SlashItem[]>>((acc, item) => {
    if (!acc[item.category]) acc[item.category] = []
    acc[item.category].push(item)
    return acc
  }, {})

  return (
    <div
      ref={menuRef}
      className="slash-menu"
      style={{
        position: 'fixed',
        left: slashMenu.position?.x ?? 0,
        top: slashMenu.position?.y ?? 0,
      }}
      contentEditable={false}
    >
      <div className="slash-menu-search">
        <input
          type="text"
          className="slash-menu-input"
          value={slashMenu.search}
          onChange={e => setSlashMenuSearch(e.target.value)}
          placeholder="Filter..."
          autoFocus
          onKeyDown={e => e.stopPropagation()}
        />
      </div>
      <div className="slash-menu-items">
        {Object.entries(grouped).map(([category, items]) => (
          <div key={category} className="slash-menu-group">
            <div className="slash-menu-category">{category}</div>
            {items.map((item, idx) => {
              const globalIdx = filtered.indexOf(item)
              return (
                <button
                  key={item.type}
                  type="button"
                  className={`slash-menu-item ${globalIdx === selectedIndex ? 'selected' : ''}`}
                  onClick={() => handleSelect(item)}
                  onMouseEnter={() => setSelectedIndex(globalIdx)}
                >
                  <span className="slash-menu-item-icon">{item.icon}</span>
                  <span className="slash-menu-item-label">{item.label}</span>
                </button>
              )
            })}
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="slash-menu-empty">No results</div>
        )}
      </div>
    </div>
  )
}
