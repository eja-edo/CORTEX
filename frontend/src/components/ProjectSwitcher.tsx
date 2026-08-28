import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, MoreVertical, Pencil, Plus } from 'lucide-react'
import type { Project } from '../types'
import { strings } from '../i18n/strings'
import { useConfirmDialog } from '../hooks/useConfirmDialog'
import { useToast } from '../hooks/useToast'

/**
 * Bộ chuyển dự án ở đầu sidebar.
 *
 * Kế thừa hình dạng của bộ chuyển workspace từng đứng ở đây (đã gỡ cùng
 * toàn bộ khái niệm workspace — DESIGN 11.4), gồm cả lớp CSS
 * `workspace-switcher-*`: đổi tên lớp là một lượt churn thuần hình thức
 * trên vài tệp `.css`, không đổi hành vi gì.
 *
 * Hai chỗ khác bộ chuyển cũ, và cả hai đều là ràng buộc thật:
 *
 * **Không có nút xoá.** `projects` không có endpoint xoá (DESIGN 9.1):
 * xoá một dự án sẽ mồ côi lịch sử `attention_log`, vốn vẫn đúng sau khi
 * thứ được nhắc biến mất. Đóng dự án là thao tác tương đương.
 *
 * **Không có "mời thành viên".** Thành viên dự án được **suy ra, không
 * mời** (P4): nhận việc từ channel của dự án là đủ để vào. Một nút mời ở
 * đây sẽ hứa một luồng không tồn tại.
 */
export function ProjectSwitcher({
    projects,
    currentProject,
    onSwitch,
    onCreate,
    onRename,
    isCollapsed,
}: {
    projects: Project[]
    currentProject: Project | null
    onSwitch: (project: Project) => void
    onCreate: (name: string) => Promise<void> | void
    onRename: (id: string, name: string) => Promise<void> | void
    isCollapsed: boolean
}) {
    const { dialog: confirmDialog } = useConfirmDialog()
    const toast = useToast()
    const [isOpen, setIsOpen] = useState(false)
    const [contextMenuId, setContextMenuId] = useState<string | null>(null)
    const [editingId, setEditingId] = useState<string | null>(null)
    const [editingName, setEditingName] = useState('')
    const [dropdownStyle, setDropdownStyle] = useState<React.CSSProperties>({})

    const containerRef = useRef<HTMLDivElement>(null)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const portalDropdownRef = useRef<HTMLDivElement>(null)
    const contextMenuRef = useRef<HTMLDivElement>(null)
    const editInputRef = useRef<HTMLInputElement>(null)

    useEffect(() => {
        function handleClickOutside(event: MouseEvent) {
            const target = event.target as Node
            const insideContainer = containerRef.current?.contains(target)
            const insidePortal = portalDropdownRef.current?.contains(target)
            const insideContextMenu = contextMenuRef.current?.contains(target)
            if (!insideContainer && !insidePortal) {
                setIsOpen(false)
                setContextMenuId(null)
            } else if (!insideContextMenu) {
                setContextMenuId(null)
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [])

    // Dropdown dựng bằng portal ra `body`: sidebar có `overflow` riêng, nên
    // một menu nằm trong nó sẽ bị cắt.
    const updateDropdownPosition = useCallback(() => {
        if (!triggerRef.current) return
        const rect = triggerRef.current.getBoundingClientRect()
        const dropdownWidth = 350
        const spaceRight = window.innerWidth - rect.left
        const left =
            spaceRight < dropdownWidth
                ? Math.max(8, window.innerWidth - dropdownWidth)
                : rect.left
        setDropdownStyle({
            position: 'fixed',
            top: `${rect.bottom + 4}px`,
            left: `${left}px`,
            minWidth: `${Math.min(dropdownWidth, window.innerWidth - 16)}px`,
        })
    }, [])

    useEffect(() => {
        if (editingId && editInputRef.current) editInputRef.current.focus()
    }, [editingId])

    const displayName = currentProject?.name ?? strings.projects.none

    const commitRename = async (id: string) => {
        const name = editingName.trim()
        setEditingId(null)
        setEditingName('')
        if (!name) return
        try {
            await onRename(id, name)
        } catch {
            toast.show({ kind: 'error', message: strings.projects.renameFailed })
        }
    }

    const handleCreate = async () => {
        setIsOpen(false)
        const name = window.prompt(strings.projects.newProjectPrompt)?.trim()
        if (!name) return
        try {
            await onCreate(name)
        } catch {
            toast.show({ kind: 'error', message: strings.projects.createFailed })
        }
    }

    return (
        <div ref={containerRef} className="workspace-switcher-container">
            <button
                ref={triggerRef}
                type="button"
                className="workspace-switcher-btn"
                onClick={() => {
                    setIsOpen((open) => !open)
                    if (!isOpen) window.requestAnimationFrame(updateDropdownPosition)
                }}
                title={displayName}
                aria-haspopup="listbox"
                aria-expanded={isOpen}
                aria-label={strings.projects.switcherLabel}
            >
                <div className="workspace-switcher-content">
                    <div
                        className="workspace-dropdown-header-avatar"
                        style={{ width: 24, height: 24, fontSize: 9 }}
                    >
                        {displayName?.[0]?.toUpperCase() || 'P'}
                    </div>
                    {!isCollapsed && (
                        <>
                            <span className="workspace-switcher-name">{displayName}</span>
                            <ChevronDown
                                size={12}
                                className={`workspace-switcher-chevron ${isOpen ? 'open' : ''}`}
                            />
                        </>
                    )}
                </div>
            </button>

            {isOpen &&
                !isCollapsed &&
                createPortal(
                    <div
                        ref={portalDropdownRef}
                        className="workspace-switcher-dropdown"
                        style={dropdownStyle}
                    >
                        {currentProject && (
                            <>
                                <div className="workspace-dropdown-section workspace-dropdown-header-section">
                                    <div className="workspace-dropdown-header-content">
                                        <div className="workspace-dropdown-header-avatar">
                                            {currentProject.name?.[0]?.toUpperCase() || 'P'}
                                        </div>
                                        <div className="workspace-dropdown-header-info">
                                            <div className="workspace-dropdown-header-name">
                                                {currentProject.name}
                                            </div>
                                            <div className="workspace-dropdown-header-metadata">
                                                {projectMeta(currentProject)}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div className="workspace-dropdown-divider" />
                            </>
                        )}

                        <div className="workspace-dropdown-section workspace-dropdown-workspaces-section">
                            <div className="workspace-dropdown-section-label">
                                {strings.projects.yourProjects}
                            </div>
                            <div className="workspace-dropdown-list">
                                {projects.map((project) => {
                                    const isActive = project.id === currentProject?.id
                                    const isEditing = editingId === project.id
                                    return (
                                        <div key={project.id} className="workspace-dropdown-item-wrapper">
                                            <button
                                                type="button"
                                                className={`workspace-dropdown-item ${isActive ? 'active' : ''}`}
                                                onClick={() => {
                                                    if (isEditing) return
                                                    onSwitch(project)
                                                    setIsOpen(false)
                                                }}
                                            >
                                                <div className="workspace-dropdown-item-content">
                                                    <div className="workspace-dropdown-item-icon">
                                                        <ProjectIcon origin={project.origin} />
                                                    </div>
                                                    <div className="workspace-dropdown-item-info">
                                                        {isEditing ? (
                                                            <input
                                                                ref={editInputRef}
                                                                type="text"
                                                                className="workspace-dropdown-edit-input"
                                                                value={editingName}
                                                                onChange={(e) => setEditingName(e.target.value)}
                                                                onBlur={() => void commitRename(project.id)}
                                                                onKeyDown={(e) => {
                                                                    if (e.key === 'Enter') void commitRename(project.id)
                                                                    if (e.key === 'Escape') {
                                                                        setEditingId(null)
                                                                        setEditingName('')
                                                                    }
                                                                }}
                                                                onClick={(e) => e.stopPropagation()}
                                                            />
                                                        ) : (
                                                            <span className="workspace-dropdown-item-name">
                                                                {project.name}
                                                            </span>
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
                                                        setContextMenuId(
                                                            contextMenuId === project.id ? null : project.id,
                                                        )
                                                    }}
                                                >
                                                    <MoreVertical size={14} />
                                                </button>
                                            )}

                                            {contextMenuId === project.id && (
                                                <div ref={contextMenuRef} className="workspace-context-menu">
                                                    <button
                                                        type="button"
                                                        className="workspace-context-menu-item"
                                                        onClick={() => {
                                                            setEditingId(project.id)
                                                            setEditingName(project.name)
                                                            setContextMenuId(null)
                                                        }}
                                                    >
                                                        <Pencil size={14} />
                                                        <span>{strings.projects.rename}</span>
                                                    </button>
                                                </div>
                                            )}
                                        </div>
                                    )
                                })}
                            </div>

                            <button
                                type="button"
                                className="workspace-dropdown-create-btn"
                                onClick={() => void handleCreate()}
                            >
                                <Plus size={14} />
                                <span>{strings.projects.newProject}</span>
                            </button>
                        </div>
                    </div>,
                    document.body,
                )}
            {confirmDialog}
        </div>
    )
}

/** Dòng phụ dưới tên dự án: nguồn gốc + số việc đang mở.
 *
 * Nguồn gốc đứng trước vì nó trả lời câu người dùng hay hỏi nhất về một dự
 * án họ không nhớ đã tạo — *"cái này ở đâu ra?"*. Dự án suy ra từ channel
 * không phải thứ ai đó bấm nút để tạo. */
function projectMeta(project: Project): string {
    const origin =
        project.origin === 'personal'
            ? strings.projects.originPersonal
            : project.origin === 'derived'
              ? strings.projects.originDerived
              : strings.projects.originManual
    return `${origin} · ${strings.projects.openCount(project.open_task_count)}`
}

function ProjectIcon({ origin }: { origin: Project['origin'] }) {
    if (origin === 'personal') {
        return (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
            </svg>
        )
    }
    if (origin === 'derived') {
        // Dấu # — dự án này *là* một channel Mezon (QĐ-2), không phải một
        // thư mục ai đó đặt tên.
        return (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="4" y1="9" x2="20" y2="9" />
                <line x1="4" y1="15" x2="20" y2="15" />
                <line x1="10" y1="3" x2="8" y2="21" />
                <line x1="16" y1="3" x2="14" y2="21" />
            </svg>
        )
    }
    return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        </svg>
    )
}
