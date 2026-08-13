import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { LogOut, Settings } from 'lucide-react'
import type { User } from '../types'

interface UserMenuProps {
  user: User | null
  onOpenSettings: () => void
  onLogout: () => void
}

export function UserMenu({ user, onOpenSettings, onLogout }: UserMenuProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [dropdownStyle, setDropdownStyle] = useState<React.CSSProperties>({})
  const triggerRef = useRef<HTMLButtonElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const userInitial = user?.full_name?.[0]?.toUpperCase() ?? user?.email?.[0]?.toUpperCase() ?? '?'

  const updateDropdownPosition = useCallback(() => {
    if (!triggerRef.current) return
    const rect = triggerRef.current.getBoundingClientRect()
    const dropdownWidth = 260
    setDropdownStyle({
      position: 'fixed',
      top: `${rect.bottom + 8}px`,
      left: `${Math.max(8, rect.right - dropdownWidth)}px`,
      minWidth: `${dropdownWidth}px`,
    })
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
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node
      if (triggerRef.current?.contains(target)) return
      if (dropdownRef.current?.contains(target)) return
      setIsOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="user-avatar"
        title={user?.email}
        onClick={() => {
          setIsOpen(prev => !prev)
          if (!isOpen) window.requestAnimationFrame(() => updateDropdownPosition())
        }}
      >
        {userInitial}
      </button>

      {isOpen && createPortal(
        <div ref={dropdownRef} className="user-menu-dropdown" style={dropdownStyle}>
          <div className="user-menu-account">
            <div className="user-menu-account-avatar">{userInitial}</div>
            <div className="user-menu-account-info">
              <div className="user-menu-account-name">{user?.full_name || 'User'}</div>
              <div className="user-menu-account-email">{user?.email}</div>
            </div>
          </div>

          <div className="user-menu-divider" />

          <button
            type="button"
            className="user-menu-item"
            onClick={() => {
              onOpenSettings()
              setIsOpen(false)
            }}
          >
            <Settings size={15} />
            <span>Cài đặt</span>
          </button>

          <button
            type="button"
            className="user-menu-item danger"
            onClick={() => {
              onLogout()
              setIsOpen(false)
            }}
          >
            <LogOut size={15} />
            <span>Đăng xuất</span>
          </button>
        </div>,
        document.body,
      )}
    </>
  )
}
