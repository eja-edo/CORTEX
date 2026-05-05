import { useState, useRef, useEffect } from 'react'
import { ChevronDown, Check, Shield, Users, Eye, Plus, MoreVertical, Pencil, Trash2, UserPlus } from 'lucide-react'
import type { Workspace } from '../types'

interface WorkspaceSwitcherProps {
  workspaces: Workspace[]
  currentWorkspace: Workspace | null
  onSwitch: (workspace: Workspace) => void
  onCreateWorkspace: () => void
  onRenameWorkspace: (id: string, name: string) => Promise<boolean>
  onDeleteWorkspace: (id: string) => Promise<boolean>
  onManageMembers: (workspace: Workspace) => void
  isCollapsed: boolean
}

export function WorkspaceSwitcher({
  workspaces,
  currentWorkspace,
  onSwitch,
  onCreateWorkspace,
  onRenameWorkspace,
  onDeleteWorkspace,
  onManageMembers,
  isCollapsed,
}: WorkspaceSwitcherProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [contextMenuId, setContextMenuId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)
  const contextMenuRef = useRef<HTMLDivElement>(null)
  const editInputRef = useRef<HTMLInputElement>(null)

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false)
        setContextMenuId(null)
      }
      if (contextMenuRef.current && !contextMenuRef.current.contains(event.target as Node)) {
        setContextMenuId(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Focus edit input when editing starts
  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus()
      editInputRef.current.select()
    }
  }, [editingId])

  const displayWorkspace = currentWorkspace || workspaces[0]
  if (!displayWorkspace) return null

  const getRoleIcon = (role: string) => {
    switch (role) {
      case 'owner':
        return <Shield size={12} />
      case 'editor':
        return <Users size={12} />
      case 'viewer':
        return <Eye size={12} />
      default:
        return null
    }
  }

  const getRoleBadgeColor = (role: string) => {
    switch (role) {
      case 'owner':
        return { bg: '#f2f9ff', text: '#097fe8' }
      case 'editor':
        return { bg: '#f0faf0', text: '#1aae39' }
      case 'viewer':
        return { bg: '#f6f5f4', text: '#615d59' }
      default:
        return { bg: '#f6f5f4', text: '#615d59' }
    }
  }

  const handleRename = async (id: string) => {
    if (!editingName.trim()) {
      setEditingId(null)
      return
    }
    await onRenameWorkspace(id, editingName.trim())
    setEditingId(null)
    setEditingName('')
  }

  const handleDelete = async (workspace: Workspace) => {
    if (workspace.is_personal) {
      alert('Cannot delete personal workspace')
      return
    }
    if (window.confirm(`Are you sure you want to delete "${workspace.name}"? This action cannot be undone.`)) {
      const success = await onDeleteWorkspace(workspace.id)
      if (success) {
        setContextMenuId(null)
      }
    }
  }

  return (
    <div ref={containerRef} className="workspace-switcher-container">
      {/* Workspace Switcher Button */}
      <button
        type="button"
        className="workspace-switcher-btn"
        onClick={() => setIsOpen(!isOpen)}
        title={displayWorkspace.name}
      >
        <div className="workspace-switcher-content">
          <div className="workspace-switcher-icon">
            {displayWorkspace.is_personal ? (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                <polyline points="9 22 9 12 15 12 15 22" />
              </svg>
            )}
          </div>
          {!isCollapsed && (
            <>
              <span className="workspace-switcher-name">{displayWorkspace.name}</span>
              <span
                className="workspace-switcher-role-badge"
                style={{
                  background: getRoleBadgeColor(displayWorkspace.my_role).bg,
                  color: getRoleBadgeColor(displayWorkspace.my_role).text,
                }}
              >
                {getRoleIcon(displayWorkspace.my_role)}
                <span>{displayWorkspace.my_role}</span>
              </span>
              <ChevronDown size={12} className={`workspace-switcher-chevron ${isOpen ? 'open' : ''}`} />
            </>
          )}
        </div>
      </button>

      {/* Workspace Dropdown */}
      {isOpen && !isCollapsed && (
        <div className="workspace-switcher-dropdown">
          <div className="workspace-dropdown-header">Switch workspace</div>
          <div className="workspace-dropdown-list">
            {workspaces.map((workspace) => {
              const isActive = currentWorkspace && workspace.id === currentWorkspace.id
              const isEditing = editingId === workspace.id
              return (
                <div key={workspace.id} className="workspace-dropdown-item-wrapper">
                  <button
                    type="button"
                    className={`workspace-dropdown-item ${isActive ? 'active' : ''}`}
                    onClick={() => {
                      if (!isEditing) {
                        onSwitch(workspace)
                        setIsOpen(false)
                      }
                    }}
                  >
                    <div className="workspace-dropdown-item-content">
                      <div className="workspace-dropdown-item-icon">
                        {workspace.is_personal ? (
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                            <circle cx="12" cy="7" r="4" />
                          </svg>
                        ) : (
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                            <polyline points="9 22 9 12 15 12 15 22" />
                          </svg>
                        )}
                      </div>
                      <div className="workspace-dropdown-item-info">
                        {isEditing ? (
                          <input
                            ref={editInputRef}
                            type="text"
                            className="workspace-dropdown-edit-input"
                            value={editingName}
                            onChange={(e) => setEditingName(e.target.value)}
                            onBlur={() => handleRename(workspace.id)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') handleRename(workspace.id)
                              if (e.key === 'Escape') {
                                setEditingId(null)
                                setEditingName('')
                              }
                            }}
                            onClick={(e) => e.stopPropagation()}
                          />
                        ) : (
                          <span className="workspace-dropdown-item-name">{workspace.name}</span>
                        )}
                        <span
                          className="workspace-dropdown-item-role"
                          style={{
                            color: getRoleBadgeColor(workspace.my_role).text,
                          }}
                        >
                          {getRoleIcon(workspace.my_role)}
                          {workspace.my_role}
                        </span>
                      </div>
                    </div>
                    {isActive && !isEditing && (
                      <Check size={14} className="workspace-dropdown-check" />
                    )}
                  </button>

                  {/* 3-dot context menu button */}
                  {!isEditing && (
                    <button
                      type="button"
                      className="workspace-dropdown-item-actions"
                      onClick={(e) => {
                        e.stopPropagation()
                        setContextMenuId(contextMenuId === workspace.id ? null : workspace.id)
                      }}
                    >
                      <MoreVertical size={14} />
                    </button>
                  )}

                  {/* Context Menu */}
                  {contextMenuId === workspace.id && (
                    <div ref={contextMenuRef} className="workspace-context-menu">
                      <button
                        type="button"
                        className="workspace-context-menu-item"
                        onClick={() => {
                          setEditingId(workspace.id)
                          setEditingName(workspace.name)
                          setContextMenuId(null)
                        }}
                      >
                        <Pencil size={14} />
                        <span>Rename</span>
                      </button>
                      <button
                        type="button"
                        className="workspace-context-menu-item"
                        onClick={() => {
                          onManageMembers(workspace)
                          setContextMenuId(null)
                          setIsOpen(false)
                        }}
                      >
                        <UserPlus size={14} />
                        <span>Manage Members</span>
                      </button>
                      {!workspace.is_personal && (
                        <button
                          type="button"
                          className="workspace-context-menu-item danger"
                          onClick={() => handleDelete(workspace)}
                        >
                          <Trash2 size={14} />
                          <span>Delete</span>
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
          
          {/* Create Workspace Button */}
          <div className="workspace-dropdown-footer">
            <button
              type="button"
              className="workspace-dropdown-create-btn"
              onClick={() => {
                onCreateWorkspace()
                setIsOpen(false)
              }}
            >
              <Plus size={14} />
              <span>Create workspace</span>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
