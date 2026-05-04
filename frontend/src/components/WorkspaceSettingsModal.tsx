import { useState, useEffect, useRef } from 'react'
import {
    X, Settings, Users, Bell, Link, Trash2,
    ChevronRight, Check, Copy, RefreshCw, UserPlus,
    Eye, Crown, Edit3, MoreHorizontal, Search, LogOut
} from 'lucide-react'
import type { Workspace } from '../types'

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
    { id: 'general', label: 'General', icon: <Settings size={15} /> },
    { id: 'people', label: 'People & permissions', icon: <Users size={15} /> },
    { id: 'notifications', label: 'Notifications', icon: <Bell size={15} /> },
    { id: 'integrations', label: 'Integrations', icon: <Link size={15} /> },
    { id: 'danger', label: 'Danger zone', icon: <Trash2 size={15} /> },
]

const ROLE_META = {
    owner: { label: 'Owner', icon: <Crown size={12} />, color: '#dfab01', bg: '#fefae0' },
    editor: { label: 'Editor', icon: <Edit3 size={12} />, color: '#0f7b6c', bg: '#edfaf7' },
    viewer: { label: 'Viewer', icon: <Eye size={12} />, color: '#787774', bg: '#f7f7f5' },
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
                <h2>General</h2>
                <p>Manage your workspace settings and preferences.</p>
            </div>

            <div className="ws-settings-card">
                <div className="ws-settings-field-label">Workspace name</div>
                <div className="ws-settings-field-row">
                    <input
                        className="ws-settings-input"
                        value={name}
                        onChange={e => setName(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleSave()}
                        placeholder="Workspace name"
                    />
                    <button
                        className={`ws-settings-save-btn ${isDirty ? 'active' : ''} ${saved ? 'saved' : ''}`}
                        onClick={handleSave}
                        disabled={!isDirty || saving}
                    >
                        {saving ? <RefreshCw size={13} className="ws-spin" /> : saved ? <><Check size={13} /> Saved</> : 'Save'}
                    </button>
                </div>
                <div className="ws-settings-field-hint">This is the name that appears in the sidebar and workspace switcher.</div>
            </div>

            <div className="ws-settings-card">
                <div className="ws-settings-field-label">Workspace ID</div>
                <div className="ws-settings-field-row">
                    <div className="ws-settings-id-display">{workspace.id}</div>
                    <button className="ws-settings-copy-btn" onClick={copyId} title="Copy ID">
                        {copied ? <Check size={13} /> : <Copy size={13} />}
                        {copied ? 'Copied' : 'Copy'}
                    </button>
                </div>
                <div className="ws-settings-field-hint">Use this ID when working with the API or sharing workspace links.</div>
            </div>

            <div className="ws-settings-card">
                <div className="ws-settings-field-label">Workspace type</div>
                <div className="ws-settings-type-badge">
                    {workspace.is_personal ? (
                        <><span className="ws-type-dot personal" />Personal workspace</>
                    ) : (
                        <><span className="ws-type-dot team" />Team workspace</>
                    )}
                </div>
                <div className="ws-settings-field-hint">
                    {workspace.is_personal
                        ? 'Personal workspaces are private to you and cannot be shared.'
                        : 'Team workspaces can be shared with members.'}
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
        else setAddError('Could not add member. Make sure the email is correct.')
    }

    return (
        <div className="ws-settings-section">
            <div className="ws-settings-section-header">
                <h2>People & permissions</h2>
                <p>Manage who has access to this workspace and what they can do.</p>
            </div>

            {!workspace.is_personal && (
                <div className="ws-settings-card">
                    <div className="ws-settings-field-label">Invite members</div>
                    <form className="ws-people-invite-row" onSubmit={handleAdd}>
                        <input
                            className="ws-settings-input"
                            placeholder="name@company.com"
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
                            <option value="editor">Can edit</option>
                            <option value="viewer">Can view</option>
                        </select>
                        <button type="submit" className="ws-invite-btn" disabled={isAdding || !email.trim()}>
                            {isAdding ? <RefreshCw size={13} className="ws-spin" /> : <UserPlus size={13} />}
                            Invite
                        </button>
                    </form>
                    {addError && <div className="ws-settings-error">{addError}</div>}
                </div>
            )}

            <div className="ws-settings-card">
                <div className="ws-people-header">
                    <div className="ws-settings-field-label" style={{ marginBottom: 0 }}>
                        Members <span className="ws-member-count">{members.length}</span>
                    </div>
                    {members.length > 3 && (
                        <div className="ws-people-search">
                            <Search size={12} />
                            <input
                                placeholder="Filter by name or email"
                                value={search}
                                onChange={e => setSearch(e.target.value)}
                            />
                        </div>
                    )}
                </div>

                <div className="ws-member-list">
                    {filtered.length === 0 ? (
                        <div className="ws-empty-members">No members found</div>
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
                                            {isCurrentUser && <span className="ws-you-badge">You</span>}
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
                                                    <option value="editor">Can edit</option>
                                                    <option value="viewer">Can view</option>
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
                                                                    <LogOut size={12} />Remove from workspace
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
        { key: 'noteUpdates' as const, label: 'Note updates', desc: 'When someone edits a note in this workspace' },
        { key: 'memberJoins' as const, label: 'New members', desc: 'When someone joins the workspace' },
        { key: 'mentions' as const, label: 'Mentions', desc: 'When you are @mentioned in a note' },
        { key: 'weeklyDigest' as const, label: 'Weekly digest', desc: 'A summary of activity every week' },
    ]

    return (
        <div className="ws-settings-section">
            <div className="ws-settings-section-header">
                <h2>Notifications</h2>
                <p>Choose what you want to be notified about in this workspace.</p>
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
        { name: 'Google Calendar', desc: 'Sync events and schedules', icon: '📅', connected: false },
        { name: 'Slack', desc: 'Get notifications in Slack', icon: '💬', connected: false },
        { name: 'GitHub', desc: 'Link repositories and issues', icon: '🐙', connected: false },
    ]

    return (
        <div className="ws-settings-section">
            <div className="ws-settings-section-header">
                <h2>Integrations</h2>
                <p>Connect your workspace with other tools and services.</p>
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
                            {item.connected ? <><Check size={12} />Connected</> : 'Connect'}
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
                <h2>Danger zone</h2>
                <p>These actions are permanent and cannot be undone.</p>
            </div>

            <div className="ws-settings-card danger-card">
                <div className="ws-danger-row">
                    <div>
                        <div className="ws-danger-label">Delete this workspace</div>
                        <div className="ws-danger-desc">
                            Permanently delete <strong>{workspace.name}</strong> and all its contents.
                            This action cannot be undone.
                        </div>
                    </div>
                </div>

                {!canDelete ? (
                    <div className="ws-danger-blocked">
                        {workspace.is_personal
                            ? 'Personal workspaces cannot be deleted.'
                            : 'Only the workspace owner can delete it.'}
                    </div>
                ) : (
                    <div className="ws-danger-confirm-area">
                        <div className="ws-danger-confirm-label">
                            Type <strong>{workspace.name}</strong> to confirm
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
                            Delete workspace
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
                            <div className="ws-settings-workspace-sub">Settings</div>
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
                        <button className="ws-settings-close-btn" onClick={onClose} title="Close">
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