import { useState, useRef, useEffect, useCallback, type DragEvent } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, ChevronDown, ChevronRight, Plus, StickyNote, Zap, Terminal, Brain, GitBranch, Timer, Globe } from 'lucide-react'
import { NODE_CONFIGS, getNodeColor, type NodeCategory, type NodeConfig } from './nodeConfig'

type CategoryGroup = {
  key: NodeCategory
  label: string
  icon: typeof Zap
  items: NodeConfig[]
}

const CATEGORIES: CategoryGroup[] = [
  { key: 'trigger', label: 'Triggers', icon: Zap, items: [] },
  { key: 'webhook', label: 'Webhooks', icon: Globe, items: [] },
  { key: 'action', label: 'Actions', icon: Terminal, items: [] },
  { key: 'ai', label: 'AI', icon: Brain, items: [] },
  { key: 'condition', label: 'Conditions', icon: GitBranch, items: [] },
  { key: 'wait', label: 'Wait', icon: Timer, items: [] },
]

CATEGORIES.forEach(cat => {
  cat.items = NODE_CONFIGS.filter(n => n.category === cat.key)
})

type NodePaletteProps = {
  onDragStart: (event: DragEvent, type: string) => void
  onAddStickyNote?: () => void
}

export function NodePalette({ onDragStart, onAddStickyNote }: NodePaletteProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [collapsed, setCollapsed] = useState<Set<NodeCategory>>(new Set())
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const toggleCategory = useCallback((key: NodeCategory) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const query = search.toLowerCase().trim()

  const visibleCategories = CATEGORIES.filter(cat => {
    if (cat.items.length === 0) return false
    if (!query) return true
    return cat.items.some(item =>
      item.label.toLowerCase().includes(query) ||
      item.type.toLowerCase().includes(query)
    )
  })

  return (
    <>
      <button
        type="button"
        className="wf-palette-toggle"
        onClick={() => setOpen(prev => !prev)}
        title="Node library"
      >
        <Plus size={18} />
      </button>

      <button
        type="button"
        className="wf-sticky-btn"
        onClick={() => onAddStickyNote?.()}
        title="Add sticky note"
      >
        <StickyNote size={16} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.aside
            ref={panelRef}
            className="wf-palette"
            initial={{ opacity: 0, x: -20, scale: 0.95 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: -20, scale: 0.95 }}
            transition={{ type: 'spring', stiffness: 400, damping: 30 }}
          >
            <div>
              <p className="wf-palette-title">NODE LIBRARY</p>
              <div className="wf-palette-search-wrap">
                <Search size={14} className="wf-palette-search-icon" />
                <input
                  type="text"
                  className="wf-palette-search"
                  placeholder="Search nodes..."
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  autoFocus
                />
              </div>
            </div>

            <div className="wf-palette-sections">
              {visibleCategories.map(cat => {
                const isOpen = !collapsed.has(cat.key)
                const filteredItems = query
                  ? cat.items.filter(item =>
                      item.label.toLowerCase().includes(query) ||
                      item.type.toLowerCase().includes(query)
                    )
                  : cat.items

                if (filteredItems.length === 0) return null

                return (
                  <div key={cat.key} className="wf-palette-section">
                    <div className="wf-palette-section-header">
                      <button
                        type="button"
                        className="wf-palette-category"
                        onClick={() => toggleCategory(cat.key)}
                      >
                        {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      </button>
                      <span className="wf-palette-section-label">{cat.label}</span>
                      <span className="wf-palette-section-count">{filteredItems.length}</span>
                    </div>

                    <AnimatePresence initial={false}>
                      {isOpen && (
                        <motion.div
                          key="items"
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2 }}
                          className="wf-palette-items-wrap"
                        >
                          {filteredItems.map(item => (
                            <div
                              key={item.type}
                              className="wf-palette-item"
                              draggable
                              onDragStart={e => onDragStart(e, item.type)}
                            >
                              <span
                                className="wf-palette-item-icon"
                                style={{ color: getNodeColor(item.type) } as React.CSSProperties}
                              >
                                <item.icon size={16} />
                              </span>
                              <span className="wf-palette-item-label">{item.label}</span>
                            </div>
                          ))}
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                )
              })}
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </>
  )
}
