import { useState, useEffect, useRef } from 'react'
import {
    X, Settings, Users, Bell, Link, Trash2,
    ChevronRight, Check, Copy, RefreshCw, UserPlus,
    Eye, Crown, Edit3, MoreHorizontal, Search, LogOut
} from 'lucide-react'
import type { Workspace } from '../types'
import { strings } from '../i18n/strings'

interface WorkspaceMember {
    id: string
    user_id: string
    email: string
    full_name: string | null
    role: 'owner' | 'editor' | 'viewer'
    joined_at?: string
}

interface WorkspaceSettingsModalProps {
    workspace: Workspace
    onClose: () => void
    onRenameWorkspace: (id: string, name: string) => Promise<boolean>
    onDeleteWorkspace: (id: string) => Promise<boolean>
    onAddMember: (email: string, role: 'editor' | 'viewer') => Promise<boolean>
    onRemoveMember: (userId: string) => Promise<boolean>
    onChangeRole: (userId: string, role: 'editor' | 'viewer') => Promise<boolean>
    members?: WorkspaceMember[]
    currentUserId?: string
}

type SettingsTab = 'general' | 'people' | 'notifications' | 'integrations' | 'danger'

const NAV_ITEMS: { id: SettingsTab; label: string; icon: React.ReactNode; description?: string }[] = [
    { id: 'general', label: strings.workspace.settings.general.title, icon: <Settings size={15} /> },
    { id: 'people', label: strings.workspace.settings.people.title, icon: <Users size={15} /> },
    { id: 'notifications', label: strings.workspace.settings.notifications.title, icon: <Bell size={15} /> },
    { id: 'integrations', label: strings.workspace.settings.integrations.title, icon: <Link size={15} /> },
    { id: 'danger', label: strings.workspace.settings.danger.title, icon: <Trash2 size={15} /> },
]

const ROLE_META = {
    // Themed tokens, not literals: the previous hex pairs were light-theme
    // values that stayed light on all five dark themes, and owner's
    // #dfab01-on-#fefae0 measured 2.1:1 even on light.
    owner: { label: 'Owner', icon: <Crown size={12} />, color: 'var(--yellow)', bg: 'var(--yellow-light)' },
    editor: { label: 'Editor', icon: <Edit3 size={12} />, color: 'var(--green)', bg: 'var(--green-light)' },
    viewer: { label: 'Viewer', icon: <Eye size={12} />, color: 'var(--text-secondary)', bg: 'var(--bg-secondary)' },
}

function Avatar({ name, email, size = 32 }: { name?: string | null; email?: string; size?: number }) {
    const initial = name?.[0]?.toUpperCase() || email?.[0]?.toUpperCase() || '?'
    const colors = [
        ['#dbeafe', '#1d4ed8'], ['#dcfce7', '#15803d'], ['#fce7f3', '#be185d'],
        ['#ede9fe', '#7c3aed'], ['#ffedd5', '#c2410c'], ['#cffafe', '#0e7490'],
    ]
    const idx = (initial.charCodeAt(0) || 0) % colors.length
    const [bg, text] = colors[idx]
    return (
        <div style={{
            width: size, height: size, borderRadius: '50%', background: bg, color: text,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: size * 0.38, fontWeight: 700, flexShrink: 0, letterSpacing: '-0.01em',
        }}>{initial}</div>
    )
}

// ── General Tab ──
function GeneralTab({ workspace, onRename }: {
    workspace: Workspace
    onRename: (name: string) => Promise<boolean>
}) {
    const [name, setName] = useState(workspace.name)
    const [saving, setSaving] = useState(false)
    const [saved, setSaved] = useState(false)
    const [copied, setCopied] = useState(false)
    const isDirty = name.trim() !== workspace.name && name.trim() !== ''

    const handleSave = async () => {
        if (!isDirty || saving) return
        setSaving(true)
        const ok = await onRename(name.trim())
        setSaving(false)
        if (ok) { setSaved(true); setTimeout(() => setSaved(false), 2000) }
    }

    const copyId = () => {
        navigator.clipboard.writeText(workspace.id)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
    }

    return (
        <div className="ws-settings-section">
            <div className="ws-settings-section-header">
                <h2>{strings.workspace.settings.general.title}</h2>
                <p>{strings.workspace.settings.general.desc}</p>
            </div>

            <div className="ws-settings-card">
                <div className="ws-settings-field-label">{strings.workspace.settings.general.nameLabel}</div>
                <div className="ws-settings-field-row">
                    <input
                        className="ws-settings-input"
                        value={name}
                        onChange={e => setName(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleSave()}
                        placeholder={strings.workspace.settings.general.namePlaceholder}
                    />
                    <button
                        className={`ws-settings-save-btn ${isDirty ? 'active' : ''} ${saved ? 'saved' : ''}`}
                        onClick={handleSave}
                        disabled={!isDirty || saving}
                    >
                        {saving ? <RefreshCw size={13} className="ws-spin" /> : saved ? <><Check size={13} /> {strings.workspace.settings.general.saved}</> : strings.workspace.settings.general.saveBtn}
                    </button>
                </div>
                <div className="ws-settings-field-hint">{strings.workspace.settings.general.nameHint}</div>
            </div>

            <div className="ws-settings-card">
                <div className="ws-settings-field-label">{strings.workspace.settings.general.idLabel}</div>
                <div className="ws-settings-field-row">
                    <div className="ws-settings-id-display">{workspace.id}</div>
                    <button className="ws-settings-copy-btn" onClick={copyId} title={strings.workspace.settings.general.copyIdTooltip}>
                        {copied ? <Check size={13} /> : <Copy size={13} />}
                        {copied ? strings.workspace.settings.general.copied : strings.workspace.settings.general.copyId}
                    </button>
                </div>
                <div className="ws-settings-field-hint">{strings.workspace.settings.general.copyIdHint}</div>
            </div>

            <div className="ws-settings-card">
                <div className="ws-settings-field-label">{strings.workspace.settings.general.typeLabel}</div>
                <div className="ws-settings-type-badge">
                    {workspace.is_personal ? (
                        <><span className="ws-type-dot personal" />{strings.workspace.settings.general.personal}</>
                    ) : (
                        <><span className="ws-type-dot team" />{strings.workspace.settings.general.team}</>
                    )}
                </div>
                <div className="ws-settings-field-hint">
                    {workspace.is_personal
                        ? strings.workspace.settings.general.personalHint
                        : strings.workspace.settings.general.teamHint}
                </div>
            </div>
        </div>
    )
}

// ── People Tab ──
function PeopleTab({ workspace, members, onAddMember, onRemoveMember, onChangeRole, currentUserId }: {
    workspace: Workspace
    members: WorkspaceMember[]
    onAddMember: (email: string, role: 'editor' | 'viewer') => Promise<boolean>
    onRemoveMember: (userId: string) => Promise<boolean>
    onChangeRole: (userId: string, role: 'editor' | 'viewer') => Promise<boolean>
    currentUserId?: string
}) {
    const [email, setEmail] = useState('')
    const [role, setRole] = useState<'editor' | 'viewer'>('editor')
    const [isAdding, setIsAdding] = useState(false)
    const [addError, setAddError] = useState('')
    const [search, setSearch] = useState('')
    const [menuOpenFor, setMenuOpenFor] = useState<string | null>(null)

    const filtered = members.filter(m =>
        m.email.toLowerCase().includes(search.toLowerCase()) ||
        (m.full_name?.toLowerCase() ?? '').includes(search.toLowerCase())
    )

    const handleAdd = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!email.trim()) return
        setIsAdding(true)
        setAddError('')
        const ok = await onAddMember(email.trim(), role)
        setIsAdding(false)
        if (ok) setEmail('')
        else setAddError(strings.workspace.settings.people.inviteError)
    }

    return (
        <div className="ws-settings-section">
            <div className="ws-settings-section-header">
                <h2>{strings.workspace.settings.people.title}</h2>
                <p>{strings.workspace.settings.people.desc}</p>
            </div>

            {!workspace.is_personal && (
                <div className="ws-settings-card">
                    <div className="ws-settings-field-label">{strings.workspace.settings.people.inviteLabel}</div>
                    <form className="ws-people-invite-row" onSubmit={handleAdd}>
                        <input
                            className="ws-settings-input"
                            placeholder={strings.workspace.settings.people.emailPlaceholder}
                            value={email}
                            onChange={e => setEmail(e.target.value)}
                            type="email"
                            disabled={isAdding}
                        />
                        <select
                            className="ws-settings-select"
                            value={role}
                            onChange={e => setRole(e.target.value as 'editor' | 'viewer')}
                            disabled={isAdding}
                        >
                            <option value="editor">{strings.workspace.settings.people.roleEditor}</option>
                            <option value="viewer">{strings.workspace.settings.people.roleViewer}</option>
                        </select>
                        <button type="submit" className="ws-invite-btn" disabled={isAdding || !email.trim()}>
                            {isAdding ? <RefreshCw size={13} className="ws-spin" /> : <UserPlus size={13} />}
                            {strings.workspace.settings.people.inviteBtn}
                        </button>
                    </form>
                    {addError && <div className="ws-settings-error">{addError}</div>}
                </div>
            )}

            <div className="ws-settings-card">
                <div className="ws-people-header">
                    <div className="ws-settings-field-label" style={{ marginBottom: 0 }}>
                        {strings.workspace.settings.people.membersLabel} <span className="ws-member-count">{members.length}</span>
                    </div>
                    {members.length > 3 && (
                        <div className="ws-people-search">
                            <Search size={12} />
                            <input
                                placeholder={strings.workspace.settings.people.searchPlaceholder}
                                value={search}
                                onChange={e => setSearch(e.target.value)}
                            />
                        </div>
                    )}
                </div>

                <div className="ws-member-list">
                    {filtered.length === 0 ? (
                        <div className="ws-empty-members">{strings.workspace.settings.people.noMembers}</div>
                    ) : (
                        filtered.map(member => {
                            const meta = ROLE_META[member.role]
                            const isCurrentUser = member.user_id === currentUserId
                            return (
                                <div key={member.user_id} className="ws-member-row">
                                    <Avatar name={member.full_name} email={member.email} size={32} />
                                    <div className="ws-member-info">
                                        <div className="ws-member-name">
                                            {member.full_name || member.email}
                                            {isCurrentUser && <span className="ws-you-badge">{strings.workspace.settings.people.youBadge}</span>}
                                        </div>
                                        {member.full_name && <div className="ws-member-email">{member.email}</div>}
                                    </div>
                                    <div className="ws-member-role-area">
                                        {member.role === 'owner' ? (
                                            <span className="ws-role-badge" style={{ background: meta.bg, color: meta.color }}>
                                                {meta.icon}{meta.label}
                                            </span>
                                        ) : (
                                            <div className="ws-member-actions-wrap">
                                                <select
                                                    className="ws-role-select"
                                                    value={member.role}
                                                    onChange={e => onChangeRole(member.user_id, e.target.value as 'editor' | 'viewer')}
                                                    style={{ color: meta.color }}
                                                >
                                                    <option value="editor">{strings.workspace.settings.people.roleEditor}</option>
                                                    <option value="viewer">{strings.workspace.settings.people.roleViewer}</option>
                                                </select>
                                                {!workspace.is_personal && (
                                                    <div className="ws-member-menu-wrap">
                                                        <button
                                                            className="ws-member-menu-btn"
                                                            onClick={() => setMenuOpenFor(menuOpenFor === member.user_id ? null : member.user_id)}
                                                        >
                                                            <MoreHorizontal size={14} />
                                                        </button>
                                                        {menuOpenFor === member.user_id && (
                                                            <div className="ws-member-menu">
                                                                <button
                                                                    className="ws-member-menu-item danger"
                                                                    onClick={() => { onRemoveMember(member.user_id); setMenuOpenFor(null) }}
                                                                >
                                                                    <LogOut size={12} />{strings.workspace.settings.people.removeAction}
                                                                </button>
                                                            </div>
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )
                        })
                    )}
                </div>
            </div>
        </div>
    )
}

// ── Notifications Tab ──
function NotificationsTab() {
    const [settings, setSettings] = useState({
        noteUpdates: true,
        memberJoins: false,
        weeklyDigest: true,
        mentions: true,
    })

    const toggle = (key: keyof typeof settings) =>
        setSettings(prev => ({ ...prev, [key]: !prev[key] }))

    const items = [
        { key: 'noteUpdates' as const, label: strings.workspace.settings.notifications.noteUpdates.label, desc: strings.workspace.settings.notifications.noteUpdates.desc },
        { key: 'memberJoins' as const, label: strings.workspace.settings.notifications.memberJoins.label, desc: strings.workspace.settings.notifications.memberJoins.desc },
        { key: 'mentions' as const, label: strings.workspace.settings.notifications.mentions.label, desc: strings.workspace.settings.notifications.mentions.desc },
        { key: 'weeklyDigest' as const, label: strings.workspace.settings.notifications.weeklyDigest.label, desc: strings.workspace.settings.notifications.weeklyDigest.desc },
    ]

    return (
        <div className="ws-settings-section">
            <div className="ws-settings-section-header">
                <h2>{strings.workspace.settings.notifications.title}</h2>
                <p>{strings.workspace.settings.notifications.desc}</p>
            </div>
            <div className="ws-settings-card">
                {items.map((item, i) => (
                    <div key={item.key} className={`ws-notif-row ${i < items.length - 1 ? 'bordered' : ''}`}>
                        <div>
                            <div className="ws-notif-label">{item.label}</div>
                            <div className="ws-notif-desc">{item.desc}</div>
                        </div>
                        <button
                            type="button"
                            className={`ws-toggle ${settings[item.key] ? 'on' : ''}`}
                            onClick={() => toggle(item.key)}
                            role="switch"
                            aria-checked={settings[item.key]}
                        >
                            <span className="ws-toggle-thumb" />
                        </button>
                    </div>
                ))}
            </div>
        </div>
    )
}

// ── Integrations Tab ──
function IntegrationsTab() {
    const integrations = [
        { name: strings.workspace.settings.integrations.googleCalendar.name, desc: strings.workspace.settings.integrations.googleCalendar.desc, icon: '📅', connected: false },
        { name: strings.workspace.settings.integrations.slack.name, desc: strings.workspace.settings.integrations.slack.desc, icon: '💬', connected: false },
        { name: strings.workspace.settings.integrations.github.name, desc: strings.workspace.settings.integrations.github.desc, icon: '🐙', connected: false },
    ]

    return (
        <div className="ws-settings-section">
            <div className="ws-settings-section-header">
                <h2>{strings.workspace.settings.integrations.title}</h2>
                <p>{strings.workspace.settings.integrations.desc}</p>
            </div>
            <div className="ws-settings-card" style={{ padding: 0, overflow: 'hidden' }}>
                {integrations.map((item, i) => (
                    <div key={item.name} className={`ws-integration-row ${i < integrations.length - 1 ? 'bordered' : ''}`}>
                        <div className="ws-integration-icon">{item.icon}</div>
                        <div className="ws-integration-info">
                            <div className="ws-integration-name">{item.name}</div>
                            <div className="ws-integration-desc">{item.desc}</div>
                        </div>
                        <button className={`ws-connect-btn ${item.connected ? 'connected' : ''}`}>
                            {item.connected ? <><Check size={12} />{strings.workspace.settings.integrations.connected}</> : strings.workspace.settings.integrations.connect}
                        </button>
                    </div>
                ))}
            </div>
        </div>
    )
}

// ── Danger Zone Tab ──
function DangerTab({ workspace, onDelete }: { workspace: Workspace; onDelete: () => Promise<boolean> }) {
    const [confirm, setConfirm] = useState('')
    const [deleting, setDeleting] = useState(false)
    const canDelete = !workspace.is_personal && workspace.my_role === 'owner'
    const confirmMatch = confirm === workspace.name

    const handleDelete = async () => {
        if (!confirmMatch || deleting) return
        setDeleting(true)
        await onDelete()
        setDeleting(false)
    }

    return (
        <div className="ws-settings-section">
            <div className="ws-settings-section-header">
                <h2>{strings.workspace.settings.danger.title}</h2>
                <p>{strings.workspace.settings.danger.desc}</p>
            </div>

            <div className="ws-settings-card danger-card">
                <div className="ws-danger-row">
                    <div>
                        <div className="ws-danger-label">{strings.workspace.settings.danger.deleteBtn}</div>
                        <div className="ws-danger-desc">
                            {strings.workspace.settings.danger.desc2(workspace.name)}
                        </div>
                    </div>
                </div>

                {!canDelete ? (
                    <div className="ws-danger-blocked">
                        {workspace.is_personal
                            ? strings.workspace.settings.danger.personalCannotDelete
                            : strings.workspace.settings.danger.onlyOwnerCanDelete}
                    </div>
                ) : (
                    <div className="ws-danger-confirm-area">
                        <div className="ws-danger-confirm-label">
                            {strings.workspace.settings.danger.confirmLabel(workspace.name)}
                        </div>
                        <input
                            className="ws-settings-input danger"
                            placeholder={workspace.name}
                            value={confirm}
                            onChange={e => setConfirm(e.target.value)}
                        />
                        <button
                            className="ws-delete-btn"
                            disabled={!confirmMatch || deleting}
                            onClick={handleDelete}
                        >
                            {deleting ? <RefreshCw size={13} className="ws-spin" /> : <Trash2 size={13} />}
                            {strings.workspace.settings.danger.deleteBtn}
                        </button>
                    </div>
                )}
            </div>
        </div>
    )
}

// ── Main Modal ──
export function WorkspaceSettingsModal({
    workspace,
    onClose,
    onRenameWorkspace,
    onDeleteWorkspace,
    onAddMember,
    onRemoveMember,
    onChangeRole,
    members = [],
    currentUserId,
}: WorkspaceSettingsModalProps) {
    const [activeTab, setActiveTab] = useState<SettingsTab>('general')
    const backdropRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
        document.addEventListener('keydown', handler)
        return () => document.removeEventListener('keydown', handler)
    }, [onClose])

    const renderContent = () => {
        switch (activeTab) {
            case 'general':
                return <GeneralTab workspace={workspace} onRename={name => onRenameWorkspace(workspace.id, name)} />
            case 'people':
                return <PeopleTab workspace={workspace} members={members} onAddMember={onAddMember} onRemoveMember={onRemoveMember} onChangeRole={onChangeRole} currentUserId={currentUserId} />
            case 'notifications':
                return <NotificationsTab />
            case 'integrations':
                return <IntegrationsTab />
            case 'danger':
                return <DangerTab workspace={workspace} onDelete={() => onDeleteWorkspace(workspace.id)} />
        }
    }

    return (
        <div
            ref={backdropRef}
            className="ws-settings-backdrop"
            onClick={e => { if (e.target === backdropRef.current) onClose() }}
        >
            <div className="ws-settings-modal">
                {/* Left Sidebar */}
                <aside className="ws-settings-sidebar">
                    <div className="ws-settings-sidebar-header">
                        <div className="ws-settings-workspace-icon">
                            {workspace.name[0]?.toUpperCase()}
                        </div>
                        <div className="ws-settings-workspace-meta">
                            <div className="ws-settings-workspace-name">{workspace.name}</div>
                            <div className="ws-settings-workspace-sub">{strings.workspace.settings.title}</div>
                        </div>
                    </div>

                    <nav className="ws-settings-nav">
                        {NAV_ITEMS.map(item => (
                            <button
                                key={item.id}
                                type="button"
                                className={`ws-settings-nav-item ${activeTab === item.id ? 'active' : ''} ${item.id === 'danger' ? 'danger' : ''}`}
                                onClick={() => setActiveTab(item.id)}
                            >
                                <span className="ws-settings-nav-icon">{item.icon}</span>
                                <span className="ws-settings-nav-label">{item.label}</span>
                                {activeTab === item.id && <ChevronRight size={12} className="ws-settings-nav-arrow" />}
                            </button>
                        ))}
                    </nav>
                </aside>

                {/* Main Content */}
                <main className="ws-settings-content">
                    <div className="ws-settings-content-header">
                        <button className="ws-settings-close-btn" onClick={onClose} title={strings.workspace.settings.closeBtn}>
                            <X size={16} />
                        </button>
                    </div>
                    <div className="ws-settings-content-body">
                        {renderContent()}
                    </div>
                </main>
            </div>
        </div>
    )
}