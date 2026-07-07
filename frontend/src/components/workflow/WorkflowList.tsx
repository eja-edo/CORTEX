import { useState, useMemo } from 'react'
import {
  Plus, Search, SlidersHorizontal, Calendar, Timer, Globe, Play,
  MoreHorizontal, Pencil, Trash2, ExternalLink, Loader,
} from 'lucide-react'
import type { WorkflowResponse, WorkflowStatus } from '../../types'

type WorkflowListProps = {
  workflows: WorkflowResponse[]
  loading: boolean
  onSelect: (id: string) => void
  onNew: () => void
  onDelete?: (id: string) => void
}

const STATUS_STYLES: Record<WorkflowStatus, { bg: string; fg: string; label: string }> = {
  draft: { bg: 'var(--bg-active)', fg: 'var(--text-tertiary)', label: 'Draft' },
  active: { bg: 'var(--green-light)', fg: 'var(--green)', label: 'Active' },
  paused: { bg: 'var(--yellow-light)', fg: 'var(--yellow)', label: 'Paused' },
  archived: { bg: 'var(--bg-hover)', fg: 'var(--text-disabled)', label: 'Archived' },
}

const TRIGGER_ICONS: Record<string, typeof Calendar> = {
  schedule: Calendar,
  webhook: Globe,
  internal_event: Timer,
  manual: Play,
}

function getTriggerIcon(type: string) {
  return TRIGGER_ICONS[type] ?? Play
}

function formatDate(dateStr: string) {
  const d = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return 'Just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function WorkflowList({ workflows, loading, onSelect, onNew, onDelete }: WorkflowListProps) {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<WorkflowStatus | 'all'>('all')
  const [sortBy, setSortBy] = useState<'updated' | 'name'>('updated')
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { all: workflows.length }
    for (const w of workflows) {
      counts[w.status] = (counts[w.status] ?? 0) + 1
    }
    return counts
  }, [workflows])

  const filtered = useMemo(() => {
    let list = workflows
    if (statusFilter !== 'all') {
      list = list.filter(w => w.status === statusFilter)
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(w => w.name.toLowerCase().includes(q) || w.description?.toLowerCase().includes(q))
    }
    list = [...list]
    if (sortBy === 'name') {
      list.sort((a, b) => a.name.localeCompare(b.name))
    } else {
      list.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    }
    return list
  }, [workflows, statusFilter, search, sortBy])

  if (loading) {
    return (
      <div className="wf-page">
        <div className="wf-list-view">
          <div className="wf-list-empty">
            <Loader size={24} className="wf-spin" />
            <p>Loading workflows...</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="wf-page">
      <div className="wf-list-view">
        <div className="wf-list-header-area">
          <div className="wf-list-header-left">
            <h1 className="wf-list-title">Workflows</h1>
            <p className="wf-list-subtitle">Automate your processes with visual workflows</p>
          </div>
          <button type="button" className="btn btn-primary" onClick={onNew}>
            <Plus size={16} />
            Create New Workflow
          </button>
        </div>

        <div className="wf-list-filter-bar">
          <div className="wf-list-search-wrap">
            <Search size={16} className="wf-list-search-icon" />
            <input
              type="text"
              className="wf-list-search-input"
              placeholder="Search workflows..."
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
          <div className="wf-list-filter-tabs">
            {(['all', 'active', 'draft'] as const).map(status => (
              <button
                key={status}
                type="button"
                className={`wf-list-filter-tab ${statusFilter === status ? 'active' : ''}`}
                onClick={() => setStatusFilter(status)}
              >
                {status === 'all' ? 'All' : status.charAt(0).toUpperCase() + status.slice(1)}
                <span className="wf-list-filter-count">{statusCounts[status] ?? 0}</span>
              </button>
            ))}
          </div>
          <div className="wf-list-sort">
            <SlidersHorizontal size={14} />
            <select
              className="wf-list-sort-select"
              value={sortBy}
              onChange={e => setSortBy(e.target.value as 'updated' | 'name')}
            >
              <option value="updated">Last updated</option>
              <option value="name">Name</option>
            </select>
          </div>
        </div>

        {filtered.length === 0 ? (
          <div className="wf-list-empty">
            {search || statusFilter !== 'all' ? (
              <>
                <p>No workflows match your filters.</p>
                <button type="button" className="btn btn-ghost" onClick={() => { setSearch(''); setStatusFilter('all') }}>
                  Clear filters
                </button>
              </>
            ) : (
              <>
                <p>No workflows yet. Create your first automation.</p>
                <button type="button" className="btn btn-primary" onClick={onNew}>
                  <Plus size={14} />
                  Create Workflow
                </button>
              </>
            )}
          </div>
        ) : (
          <div className="wf-list-cards">
            {filtered.map(w => {
              const st = STATUS_STYLES[w.status]
              const TriggerIcon = getTriggerIcon(w.trigger_type)
              return (
                <div key={w.id} className="wf-list-card-row">
                  <button
                    type="button"
                    className="wf-list-card-main"
                    onClick={() => onSelect(w.id)}
                  >
                    <div className="wf-list-card-icon" data-type={w.trigger_type}>
                      <TriggerIcon size={18} />
                    </div>
                    <div className="wf-list-card-body">
                      <div className="wf-list-card-top">
                        <span className="wf-list-card-name">{w.name}</span>
                        <span className="wf-list-card-badge" style={{ background: st.bg, color: st.fg }}>
                          {st.label}
                        </span>
                      </div>
                      {w.description && (
                        <div className="wf-list-card-desc">{w.description}</div>
                      )}
                      <div className="wf-list-card-meta">
                        <span className="wf-list-card-trigger">
                          <TriggerIcon size={12} />
                          {w.trigger_type.replace('_', ' ')}
                        </span>
                        <span className="wf-list-card-date">{formatDate(w.updated_at)}</span>
                      </div>
                    </div>
                  </button>
                  <div className="wf-list-card-actions">
                    <button
                      type="button"
                      className="wf-list-card-action-btn"
                      title="Edit"
                      onClick={() => onSelect(w.id)}
                    >
                      <Pencil size={15} />
                    </button>
                    <div className="wf-list-card-action-menu">
                      <button
                        type="button"
                        className="wf-list-card-action-btn"
                        title="More"
                        onClick={() => setOpenMenuId(openMenuId === w.id ? null : w.id)}
                      >
                        <MoreHorizontal size={15} />
                      </button>
                      {openMenuId === w.id && (
                        <>
                          <div className="wf-list-menu-backdrop" onClick={() => setOpenMenuId(null)} />
                          <div className="wf-list-menu">
                            <button
                              type="button"
                              className="wf-list-menu-item"
                              onClick={() => { setOpenMenuId(null); onSelect(w.id) }}
                            >
                              <ExternalLink size={14} />
                              Open
                            </button>
                            {onDelete && (
                              <button
                                type="button"
                                className="wf-list-menu-item danger"
                                onClick={() => { setOpenMenuId(null); onDelete(w.id) }}
                              >
                                <Trash2 size={14} />
                                Delete
                              </button>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
