import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, Check, Plus, MoreVertical, Pencil, Trash2, UserPlus, Settings } from 'lucide-react'
import type { Workspace } from '../types'
import { useConfirmDialog } from '../hooks/useConfirmDialog'
import { useToast } from '../hooks/useToast'
import { strings } from '../i18n/strings'

interface WorkspaceSwitcherProps {
  workspaces: Workspace[]
  currentWorkspace: Workspace | null
  onSwitch: (workspace: Workspace) => void
  onCreateWorkspace: () => void
  onRenameWorkspace: (id: string, name: string) => Promise<boolean>
  onDeleteWorkspace: (id: string) => Promise<boolean>
  onManageMembers: (workspace: Workspace) => void
  onOpenSettings: (workspace: Workspace) => void
  isCollapsed: boolean
  user?: { email: string; full_name: string | null } | null
  onLogout?: () => void
}

export function WorkspaceSwitcher({
  workspaces,
  currentWorkspace,
  onSwitch,
  onCreateWorkspace,
  onRenameWorkspace,
  onDeleteWorkspace,
  onManageMembers,
  onOpenSettings,
  isCollapsed,
  user,
}: WorkspaceSwitcherProps) {
  const { confirm, dialog: confirmDialog } = useConfirmDialog()
  const toast = useToast()
  const [isOpen, setIsOpen] = useState(false)
  const [contextMenuId, setContextMenuId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const [dropdownStyle, setDropdownStyle] = useState<React.CSSProperties>({})
  const containerRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const contextMenuRef = useRef<HTMLDivElement>(null)
  const editInputRef = useRef<HTMLInputElement>(null)


  const portalDropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node
      const insideContainer = containerRef.current?.contains(target)
      const insidePortalDropdown = portalDropdownRef.current?.contains(target)
      const insideContextMenu = contextMenuRef.current?.contains(target)
      if (!insideContainer && !insidePortalDropdown) {
        setIsOpen(false)
        setContextMenuId(null)
      } else if (!insideContextMenu) {
        setContextMenuId(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const updateDropdownPosition = useCallback(() => {
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      const dropdownWidth = 350
      const spaceRight = window.innerWidth - rect.left
      const left = spaceRight < dropdownWidth
        ? Math.max(8, window.innerWidth - dropdownWidth)
        : rect.left
      setDropdownStyle({
        position: 'fixed',
        top: `${rect.bottom + 4}px`,
        left: `${left}px`,
        minWidth: `${Math.min(dropdownWidth, window.innerWidth - 16)}px`,
      })
    }
  }, [])

  useEffect(() => {
    if (!isOpen) return
    updateDropdownPosition()
    window.addEventListener('scroll', updateDropdownPosition, true)
    window.addEventListener('resize', updateDropdownPosition)
    return () => {
      window.removeEventListener('scroll', updateDropdownPosition, true)
      window.removeEventListener('resize', updateDropdownPosition)
    }
  }, [isOpen, updateDropdownPosition])


  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus()
      editInputRef.current.select()
    }
  }, [editingId])

  const displayWorkspace = currentWorkspace || workspaces[0]
  if (!displayWorkspace) return null



























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
      toast.show({ kind: 'info', message: 'Không thể xoá workspace cá nhân.' })
      return
    }
    const ok = await confirm({
      title: 'Xoá workspace',
      message: `Xoá "${workspace.name}"? Toàn bộ nội dung bên trong sẽ mất và không thể hoàn tác.`,
      confirmLabel: 'Xoá',
      cancelLabel: 'Huỷ',
    })
    if (ok) {
      const success = await onDeleteWorkspace(workspace.id)
      if (success) {
        setContextMenuId(null)
        toast.show({ message: `Đã xoá workspace "${workspace.name}".` })
      } else {
        toast.show({ kind: 'error', message: 'Không xoá được workspace. Thử lại sau.' })
      }
    }
  }

  return (
    <div ref={containerRef} className="workspace-switcher-container">
      {/* Workspace Switcher Button */}
      <button
        ref={triggerRef}
        type="button"
        className="workspace-switcher-btn"
        onClick={() => {
          setIsOpen(!isOpen)
          if (!isOpen) {
            window.requestAnimationFrame(() => updateDropdownPosition())
          }
        }}
        title={displayWorkspace.name}
      >
        <div className="workspace-switcher-content">
          <div className="workspace-dropdown-header-avatar" style={{ width: 24, height: 24, fontSize: 9 }}>
            {displayWorkspace.name?.[0]?.toUpperCase() || 'W'}










          </div>
          {!isCollapsed && (
            <>
              <span className="workspace-switcher-name">{displayWorkspace.name}</span>










              <ChevronDown size={12} className={`workspace-switcher-chevron ${isOpen ? 'open' : ''}`} />
            </>
          )}
        </div>
      </button>

      {/* Workspace Dropdown (portal to escape sidebar overflow clipping) */}
      {isOpen && !isCollapsed && createPortal(
        <div
          ref={portalDropdownRef}
          className="workspace-switcher-dropdown"
          style={dropdownStyle}
        >
          {/* 1. HEADER SECTION */}
          {currentWorkspace && (
            <div className="workspace-dropdown-section workspace-dropdown-header-section">
              <div className="workspace-dropdown-header-content">
                <div className="workspace-dropdown-header-avatar">
                  {currentWorkspace.name?.[0]?.toUpperCase() || 'W'}
                </div>
                <div className="workspace-dropdown-header-info">
                  <div className="workspace-dropdown-header-name">{currentWorkspace.name}</div>
                  <div className="workspace-dropdown-header-metadata">
                    {currentWorkspace.is_personal ? strings.workspace.switcher.personalBadge : strings.workspace.switcher.teamBadge}
                  </div>
                </div>
              </div>
              <div className="workspace-dropdown-header-actions">
                <button
                  type="button"
                  className="workspace-dropdown-header-action-btn"
                    title={strings.workspace.switcher.settingsTitle}
                  onClick={() => {
                    onOpenSettings(currentWorkspace)
                    setIsOpen(false)
                  }}
                >
                  <Settings size={14} />
                </button>
                <button
                  type="button"
                  className="workspace-dropdown-header-action-btn"
                    title={strings.workspace.switcher.inviteTitle}
                  onClick={() => {
                    onManageMembers(currentWorkspace)
                    setIsOpen(false)
                  }}
                >
                  <UserPlus size={14} />
                </button>
              </div>
            </div>
          )}

          <div className="workspace-dropdown-divider" />

          {/* 2. ACCOUNT SECTION */}
          {user && (
            <div className="workspace-dropdown-section workspace-dropdown-account-section">
              <div className="workspace-dropdown-account-content">
                <div className="workspace-dropdown-account-avatar">
                  {user.full_name?.[0]?.toUpperCase() || user.email?.[0]?.toUpperCase() || '?'}
                </div>
                <div className="workspace-dropdown-account-info">
                  <div className="workspace-dropdown-account-name">{user.full_name || strings.workspace.switcher.userFallback}</div>
                  <div className="workspace-dropdown-account-email">{user.email}</div>
                </div>
              </div>
            </div>
          )}

          <div className="workspace-dropdown-divider" />









          {/* 3. WORKSPACE LIST SECTION */}
          <div className="workspace-dropdown-section workspace-dropdown-workspaces-section">
            <div className="workspace-dropdown-section-label">{strings.workspace.switcher.yourWorkspaces}</div>
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
                        </div>
                      </div>
                      {isActive && !isEditing && (
                        <Check size={14} className="workspace-dropdown-check" />
                      )}
                    </button>


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

                    {contextMenuId === workspace.id && (
                      <div ref={contextMenuRef} className="workspace-context-menu">
                        <button
                          type="button"
                          className="workspace-context-menu-item"
                          onClick={() => {
                            onOpenSettings(workspace)
                            setContextMenuId(null)
                            setIsOpen(false)
                          }}
                        >
                          <Settings size={14} />
                          <span>{strings.workspace.switcher.ctxSettings}</span>
                        </button>
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
                          <span>{strings.workspace.switcher.ctxRename}</span>
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
                          <span>{strings.workspace.switcher.ctxManageMembers}</span>
                        </button>
                        {!workspace.is_personal && (
                          <button
                            type="button"
                            className="workspace-context-menu-item danger"
                            onClick={() => handleDelete(workspace)}
                          >
                            <Trash2 size={14} />
                            <span>{strings.workspace.switcher.ctxDelete}</span>
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>

            <button
              type="button"
              className="workspace-dropdown-create-btn"
              onClick={() => {
                onCreateWorkspace()
                setIsOpen(false)
              }}
            >
              <Plus size={14} />
              <span>{strings.workspace.switcher.createWorkspaceBtn}</span>
            </button>
          </div>
        </div>,
        document.body
      )}
      {confirmDialog}
    </div>
  )
}