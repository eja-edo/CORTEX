import { useState, useRef, useEffect } from 'react'
import { ChevronDown, Check, Shield, Users, Eye } from 'lucide-react'
import type { Workspace } from '../types'

interface WorkspaceSwitcherProps {
  workspaces: Workspace[]
  currentWorkspace: Workspace | null
  onSwitch: (workspace: Workspace) => void
  isCollapsed: boolean
}

export function WorkspaceSwitcher({
  workspaces,
  currentWorkspace,
  onSwitch,
  isCollapsed,
}: WorkspaceSwitcherProps) {
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  if (!currentWorkspace) return null

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

  return (
    <div ref={containerRef} className="workspace-switcher-container">
      {/* Workspace Switcher Button */}
      <button
        type="button"
        className="workspace-switcher-btn"
        onClick={() => setIsOpen(!isOpen)}
        title={currentWorkspace.name}
      >
        <div className="workspace-switcher-content">
          <div className="workspace-switcher-icon">
            {currentWorkspace.is_personal ? (
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
              <span className="workspace-switcher-name">{currentWorkspace.name}</span>
              <span
                className="workspace-switcher-role-badge"
                style={{
                  background: getRoleBadgeColor(currentWorkspace.my_role).bg,
                  color: getRoleBadgeColor(currentWorkspace.my_role).text,
                }}
              >
                {getRoleIcon(currentWorkspace.my_role)}
                <span>{currentWorkspace.my_role}</span>
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
              const isActive = workspace.id === currentWorkspace.id
              return (
                <button
                  key={workspace.id}
                  type="button"
                  className={`workspace-dropdown-item ${isActive ? 'active' : ''}`}
                  onClick={() => {
                    onSwitch(workspace)
                    setIsOpen(false)
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
                      <span className="workspace-dropdown-item-name">{workspace.name}</span>
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
                  {isActive && (
                    <Check size={14} className="workspace-dropdown-check" />
                  )}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
