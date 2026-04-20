import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Download, Edit2, Monitor, MoreHorizontal, Pause, Play, RefreshCw, Trash2, Upload, X, Check, Clock, HardDrive, FileVideo, FileAudio, AlertCircle } from 'lucide-react'

import type { AuthRequest, Recording } from './recordingTypes'

type MediaType = 'video' | 'audio' | 'unknown'

type UploadListItem = {
    id: string
    object_key: string
    filename: string | null
    content_type: string | null
    media_type: MediaType
    total_size: number
    created_at: string
    completed_at: string | null
}

type UploadListResponse = {
    items: UploadListItem[]
    total: number
    limit: number
    offset: number
}

type UploadAccessUrlResponse = {
    upload_id: string
    object_key: string
    url: string
    expires_in_seconds: number
}

type AssetResponse = {
    id: string
    user_id: string
    workspace_id: string | null
    type: string
    status: string
    title: string | null
    description: string | null
    source_upload_id: string | null
    source_object_key: string
    metadata: Record<string, unknown> | null
    created_at: string
    updated_at: string
}

type RecordingsListProps = {
    requestWithAuth: AuthRequest
    recordings: Recording[]
    playingId: string | null
    onPlay: (recording: Recording) => void
    onPlayServerVideo: (params: { id: string; name: string; url: string }) => void
    onPlayServerAudio: (params: { id: string; name: string; url: string }) => void
    onUpload: (recordingId: string) => void
    onDownload: (recording: Recording) => void
    onDelete: (recordingId: string) => void
}

function formatDuration(seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${s.toString().padStart(2, '0')}`
}

function formatFileSize(bytes: number): string {
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatRelativeTime(isoString: string): string {
    const date = new Date(isoString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)
    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString('vi-VN')
}

function fallbackName(item: UploadListItem): string {
    if (item.filename && item.filename.trim().length > 0) return item.filename
    const parts = item.object_key.split('/')
    return parts[parts.length - 1] || item.object_key
}

function ProgressRing({ progress, size = 28 }: { progress: number; size?: number }) {
    const r = (size - 4) / 2
    const circ = 2 * Math.PI * r
    const offset = circ - (progress / 100) * circ
    return (
        <svg width={size} height={size} style={{ transform: 'rotate(-90deg)', flexShrink: 0 }}>
            <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--border)" strokeWidth="2" />
            <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--accent)" strokeWidth="2"
                strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round"
                style={{ transition: 'stroke-dashoffset 0.3s ease' }} />
        </svg>
    )
}

function InlineEdit({ value, onSave, onCancel }: { value: string; onSave: (v: string) => void; onCancel: () => void }) {
    const [draft, setDraft] = useState(value)
    const inputRef = useRef<HTMLInputElement>(null)
    useEffect(() => { inputRef.current?.focus(); inputRef.current?.select() }, [])
    const commit = () => onSave(draft.trim() || value)
    const handleKey = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter') { e.preventDefault(); commit() }
        if (e.key === 'Escape') onCancel()
    }
    return (
        <div className="rl2-inline-edit">
            <input ref={inputRef} className="rl2-inline-input" value={draft}
                onChange={e => setDraft(e.target.value)} onKeyDown={handleKey} onBlur={commit} />
            <button type="button" className="rl2-icon-btn rl2-icon-btn--confirm" onClick={commit}><Check size={11} /></button>
            <button type="button" className="rl2-icon-btn rl2-icon-btn--cancel" onClick={onCancel}><X size={11} /></button>
        </div>
    )
}

function ConfirmDelete({ name, onConfirm, onCancel }: { name: string; onConfirm: () => void; onCancel: () => void }) {
    return (
        <div className="rl2-confirm-overlay" onClick={onCancel}>
            <div className="rl2-confirm-box" onClick={e => e.stopPropagation()}>
                <div className="rl2-confirm-icon"><Trash2 size={18} /></div>
                <div className="rl2-confirm-title">Delete recording?</div>
                <div className="rl2-confirm-body"><span className="rl2-confirm-name">{name}</span> will be permanently removed.</div>
                <div className="rl2-confirm-actions">
                    <button type="button" className="rl2-confirm-btn rl2-confirm-btn--cancel" onClick={onCancel}>Cancel</button>
                    <button type="button" className="rl2-confirm-btn rl2-confirm-btn--delete" onClick={onConfirm}>Delete</button>
                </div>
            </div>
        </div>
    )
}

function ContextMenu({ items, onClose }: {
    items: { label: string; icon: React.ReactNode; danger?: boolean; disabled?: boolean; onClick: () => void }[]
    onClose: () => void
}) {
    const ref = useRef<HTMLDivElement>(null)
    useEffect(() => {
        const handler = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose() }
        document.addEventListener('mousedown', handler)
        return () => document.removeEventListener('mousedown', handler)
    }, [onClose])
    return (
        <div className="rl2-context-menu" ref={ref}>
            {items.map((item, i) => (
                <button key={i} type="button" className={`rl2-context-item ${item.danger ? 'danger' : ''}`}
                    disabled={item.disabled} onClick={() => { item.onClick(); onClose() }}>
                    <span className="rl2-context-item-icon">{item.icon}</span>{item.label}
                </button>
            ))}
        </div>
    )
}

function LocalRecordingRow({ rec, isPlaying, onPlay, onUpload, onDownload, onDelete, onRename }: {
    rec: Recording; isPlaying: boolean
    onPlay: () => void; onUpload: () => void; onDownload: () => void
    onDelete: () => void; onRename: (name: string) => void
}) {
    const [isEditing, setIsEditing] = useState(false)
    const [menuOpen, setMenuOpen] = useState(false)
    const [confirmDelete, setConfirmDelete] = useState(false)

    const menuItems = [
        { label: 'Rename', icon: <Edit2 size={12} />, onClick: () => setIsEditing(true) },
        {
            label: rec.uploadState === 'uploaded' ? 'Uploaded' : rec.uploadState === 'uploading' ? 'Uploading…' : 'Upload to cloud',
            icon: <Upload size={12} />,
            disabled: rec.uploadState === 'uploading' || rec.uploadState === 'uploaded',
            onClick: onUpload,
        },
        { label: 'Download', icon: <Download size={12} />, onClick: onDownload },
        { label: 'Delete', icon: <Trash2 size={12} />, danger: true, onClick: () => setConfirmDelete(true) },
    ]

    const statusBadge = () => {
        if (rec.uploadState === 'uploading') return <span className="rl2-badge rl2-badge--uploading"><ProgressRing progress={rec.uploadProgress ?? 0} size={14} />{rec.uploadProgress}%</span>
        if (rec.uploadState === 'uploaded') return <span className="rl2-badge rl2-badge--ok"><Check size={10} />Synced</span>
        if (rec.uploadState === 'failed') return <span className="rl2-badge rl2-badge--err"><AlertCircle size={10} />Failed</span>
        return <span className="rl2-badge rl2-badge--local">Local</span>
    }

    return (
        <>
            <div className={`rl2-row ${isPlaying ? 'rl2-row--playing' : ''}`}>
                <button type="button" className={`rl2-play-btn ${isPlaying ? 'rl2-play-btn--active' : ''}`} onClick={onPlay}>
                    {rec.uploadState === 'uploading' ? <ProgressRing progress={rec.uploadProgress ?? 0} />
                        : isPlaying ? <Pause size={14} /> : rec.type === 'audio' ? <FileAudio size={14} /> : <FileVideo size={14} />}
                </button>
                <div className="rl2-info">
                    {isEditing
                        ? <InlineEdit value={rec.name} onSave={v => { onRename(v); setIsEditing(false) }} onCancel={() => setIsEditing(false)} />
                        : <div className="rl2-name" onDoubleClick={() => setIsEditing(true)}>{rec.name}</div>}
                    <div className="rl2-meta">
                        <span><Clock size={9} />{formatDuration(rec.duration)}</span>
                        <span>{rec.type === 'audio' ? 'Audio' : 'Video'}</span>
                        {statusBadge()}
                    </div>
                    {rec.uploadError && <div className="rl2-error-text">{rec.uploadError}</div>}
                </div>
                <div className="rl2-actions">
                    <button type="button" className={`rl2-action-btn ${isPlaying ? 'active' : ''}`} onClick={onPlay}>
                        {isPlaying ? <Pause size={12} /> : <Play size={12} />}
                    </button>
                    {rec.uploadState !== 'uploaded' && (
                        <button type="button" className="rl2-action-btn" onClick={onUpload} disabled={rec.uploadState === 'uploading'} title="Upload">
                            <Upload size={12} />
                        </button>
                    )}
                    <button type="button" className="rl2-action-btn" onClick={onDownload} title="Download"><Download size={12} /></button>
                    <div className="rl2-menu-wrap">
                        <button type="button" className={`rl2-action-btn ${menuOpen ? 'active' : ''}`} onClick={() => setMenuOpen(v => !v)}>
                            <MoreHorizontal size={12} />
                        </button>
                        {menuOpen && <ContextMenu items={menuItems} onClose={() => setMenuOpen(false)} />}
                    </div>
                </div>
            </div>
            {confirmDelete && <ConfirmDelete name={rec.name} onConfirm={() => { setConfirmDelete(false); onDelete() }} onCancel={() => setConfirmDelete(false)} />}
        </>
    )
}

function ServerRecordingRow({ item, asset, isPlaying, isActionLoading, onPlay, onDownload, onDelete, onRename }: {
    item: UploadListItem; asset: AssetResponse | undefined
    isPlaying: boolean; isActionLoading: boolean
    onPlay: () => void; onDownload: () => void; onDelete: () => void; onRename: (name: string) => void
}) {
    const [isEditing, setIsEditing] = useState(false)
    const [menuOpen, setMenuOpen] = useState(false)
    const [confirmDelete, setConfirmDelete] = useState(false)
    const displayName = asset?.title || fallbackName(item)

    const menuItems = [
        { label: 'Rename', icon: <Edit2 size={12} />, onClick: () => setIsEditing(true) },
        { label: 'Download', icon: <Download size={12} />, onClick: onDownload },
        { label: 'Delete', icon: <Trash2 size={12} />, danger: true, onClick: () => setConfirmDelete(true) },
    ]

    return (
        <>
            <div className={`rl2-row ${isPlaying ? 'rl2-row--playing' : ''} ${isActionLoading ? 'rl2-row--loading' : ''}`}>
                <button type="button" className={`rl2-play-btn ${isPlaying ? 'rl2-play-btn--active' : ''}`} onClick={onPlay} disabled={isActionLoading}>
                    {isActionLoading ? <RefreshCw size={14} className="rl2-spin" />
                        : isPlaying ? <Pause size={14} /> : item.media_type === 'audio' ? <FileAudio size={14} /> : <FileVideo size={14} />}
                </button>
                <div className="rl2-info">
                    {isEditing
                        ? <InlineEdit value={displayName} onSave={v => { onRename(v); setIsEditing(false) }} onCancel={() => setIsEditing(false)} />
                        : <div className="rl2-name" onDoubleClick={() => setIsEditing(true)}>{displayName}</div>}
                    <div className="rl2-meta">
                        {item.total_size > 0 && <span><HardDrive size={9} />{formatFileSize(item.total_size)}</span>}
                        <span>{item.media_type === 'audio' ? 'Audio' : 'Video'}</span>
                        <span className="rl2-badge rl2-badge--ok"><Check size={10} />Synced</span>
                        {item.completed_at && <span><Clock size={9} />{formatRelativeTime(item.completed_at)}</span>}
                    </div>
                    {asset?.description && <div className="rl2-asset-desc">{asset.description}</div>}
                </div>
                <div className="rl2-actions">
                    <button type="button" className={`rl2-action-btn ${isPlaying ? 'active' : ''}`} onClick={onPlay} disabled={isActionLoading}>
                        {isPlaying ? <Pause size={12} /> : <Play size={12} />}
                    </button>
                    <button type="button" className="rl2-action-btn" onClick={onDownload} disabled={isActionLoading} title="Download"><Download size={12} /></button>
                    <div className="rl2-menu-wrap">
                        <button type="button" className={`rl2-action-btn ${menuOpen ? 'active' : ''}`} onClick={() => setMenuOpen(v => !v)}>
                            <MoreHorizontal size={12} />
                        </button>
                        {menuOpen && <ContextMenu items={menuItems} onClose={() => setMenuOpen(false)} />}
                    </div>
                </div>
            </div>
            {confirmDelete && <ConfirmDelete name={displayName} onConfirm={() => { setConfirmDelete(false); onDelete() }} onCancel={() => setConfirmDelete(false)} />}
        </>
    )
}

export function RecordingsList({
    requestWithAuth, recordings, playingId,
    onPlay, onPlayServerVideo, onPlayServerAudio,
    onUpload, onDownload, onDelete,
}: RecordingsListProps) {
    const [serverItems, setServerItems] = useState<UploadListItem[]>([])
    // Keyed by source_upload_id (= UploadListItem.id) for O(1) lookup
    const [assetByUploadId, setAssetByUploadId] = useState<Record<string, AssetResponse>>({})
    const [isLoadingServer, setIsLoadingServer] = useState(false)
    const [serverError, setServerError] = useState<string>('')
    const [serverActionLoadingId, setServerActionLoadingId] = useState<string | null>(null)
    const [localNames, setLocalNames] = useState<Record<string, string>>({})

    const getServerAccessUrl = useCallback(async (item: UploadListItem, disposition: 'inline' | 'attachment') => {
        const resp = await requestWithAuth<UploadAccessUrlResponse>(
            `/upload/access?upload_id=${item.id}&disposition=${disposition}`, { method: 'GET' })
        return resp.url
    }, [requestWithAuth])

    // Load all assets and build a map: source_upload_id → asset
    const loadAssets = useCallback(async () => {
        try {
            const assets = await requestWithAuth<AssetResponse[]>('/assets?limit=200&offset=0')
            const map: Record<string, AssetResponse> = {}
            for (const a of assets) {
                if (a.source_upload_id) map[a.source_upload_id] = a
            }
            setAssetByUploadId(map)
        } catch { /* non-critical */ }
    }, [requestWithAuth])

    // Fetch a single asset by asset_id and index it by source_upload_id
    const upsertAssetById = useCallback(async (assetId: string) => {
        try {
            const asset = await requestWithAuth<AssetResponse>(`/assets/${assetId}`)
            if (asset.source_upload_id) {
                setAssetByUploadId(prev => ({ ...prev, [asset.source_upload_id!]: asset }))
            }
        } catch { /* non-critical */ }
    }, [requestWithAuth])

    const loadServerItems = useCallback(async () => {
        setIsLoadingServer(true)
        setServerError('')
        try {
            const response = await requestWithAuth<UploadListResponse>('/upload/list?limit=100&offset=0', { method: 'GET' })
            setServerItems(response.items)
        } catch (err) {
            setServerError(err instanceof Error ? err.message : 'Cannot load recordings from server')
        } finally {
            setIsLoadingServer(false)
        }
    }, [requestWithAuth])

    useEffect(() => {
        void loadServerItems()
        void loadAssets()
    }, [loadServerItems, loadAssets])

    useEffect(() => {
        if (recordings.length === 0) return
        void loadServerItems()
    }, [recordings, loadServerItems])

    // When upload completes and we get an asset_id, fetch that asset
    useEffect(() => {
        for (const rec of recordings) {
            if (rec.uploadedAssetId) {
                // uploadedAssetId = asset UUID; check if we already have it indexed
                const alreadyLoaded = Object.values(assetByUploadId).some(a => a.id === rec.uploadedAssetId)
                if (!alreadyLoaded) void upsertAssetById(rec.uploadedAssetId)
            }
        }
    }, [recordings, assetByUploadId, upsertAssetById])

    const localUploadedKeys = useMemo(
        () => new Set(recordings.map(r => r.uploadedObjectKey).filter((k): k is string => Boolean(k))),
        [recordings],
    )
    const dedupedServerItems = useMemo(
        () => serverItems.filter(item => !localUploadedKeys.has(item.object_key)),
        [localUploadedKeys, serverItems],
    )
    const totalCount = recordings.length + dedupedServerItems.length

    const handleServerPlay = useCallback(async (item: UploadListItem) => {
        setServerActionLoadingId(item.id)
        setServerError('')
        try {
            const url = await getServerAccessUrl(item, 'inline')
            const name = assetByUploadId[item.id]?.title || fallbackName(item)
            if (item.media_type === 'video') onPlayServerVideo({ id: item.id, name, url })
            else onPlayServerAudio({ id: item.id, name, url })
        } catch (err) {
            setServerError(err instanceof Error ? err.message : 'Cannot play media')
        } finally {
            setServerActionLoadingId(null)
        }
    }, [getServerAccessUrl, assetByUploadId, onPlayServerVideo, onPlayServerAudio])

    const handleServerDownload = useCallback(async (item: UploadListItem) => {
        setServerActionLoadingId(item.id)
        setServerError('')
        try {
            const url = await getServerAccessUrl(item, 'attachment')
            const name = assetByUploadId[item.id]?.title || fallbackName(item)
            const a = document.createElement('a')
            a.href = url; a.download = name; a.target = '_blank'; a.rel = 'noreferrer noopener'; a.click()
        } catch (err) {
            setServerError(err instanceof Error ? err.message : 'Cannot download media')
        } finally {
            setServerActionLoadingId(null)
        }
    }, [getServerAccessUrl, assetByUploadId])

    const handleServerDelete = useCallback(async (item: UploadListItem) => {
        setServerError('')
        // asset keyed by upload_id
        const asset = assetByUploadId[item.id]
        try {
            if (asset) {
                // PATCH /api/assets/{id} sets status=ARCHIVED (soft delete per doc)
                await requestWithAuth(`/assets/${asset.id}`, { method: 'DELETE' })
                setAssetByUploadId(prev => { const n = { ...prev }; delete n[item.id]; return n })
            } else {
                await requestWithAuth(`/upload/${item.id}`, { method: 'DELETE' })
            }
            setServerItems(prev => prev.filter(s => s.id !== item.id))
        } catch (err) {
            setServerError(err instanceof Error ? err.message : 'Cannot delete recording')
        }
    }, [requestWithAuth, assetByUploadId])

    const handleServerRename = useCallback(async (item: UploadListItem, newTitle: string) => {
        setServerError('')
        const asset = assetByUploadId[item.id]

        if (asset) {
            // Happy path: asset already loaded → PATCH /api/assets/{asset.id}
            try {
                const updated = await requestWithAuth<AssetResponse>(`/assets/${asset.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: newTitle }),
                })
                setAssetByUploadId(prev => ({ ...prev, [item.id]: updated }))
            } catch (err) {
                setServerError(err instanceof Error ? err.message : 'Cannot rename recording')
            }
            return
        }

        // Asset not in map yet — reload assets list and retry
        try {
            const assets = await requestWithAuth<AssetResponse[]>('/assets?limit=200&offset=0')
            const found = assets.find(a => a.source_upload_id === item.id)
            if (found) {
                const updated = await requestWithAuth<AssetResponse>(`/assets/${found.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: newTitle }),
                })
                setAssetByUploadId(prev => ({ ...prev, [item.id]: updated }))
            } else {
                // No asset exists yet — update filename in local server item list optimistically
                setServerItems(prev => prev.map(s => s.id === item.id ? { ...s, filename: newTitle } : s))
            }
        } catch (err) {
            setServerError(err instanceof Error ? err.message : 'Cannot rename recording')
        }
    }, [requestWithAuth, assetByUploadId])

    const handleLocalRename = useCallback((id: string, name: string) => {
        setLocalNames(prev => ({ ...prev, [id]: name }))
    }, [])

    if (totalCount === 0 && !isLoadingServer) {
        return (
            <div className="rl2-empty">
                <div className="rl2-empty-icon"><Monitor size={28} /></div>
                <div className="rl2-empty-title">No recordings yet</div>
                <div className="rl2-empty-sub">Start screen recording or audio capture above</div>
            </div>
        )
    }

    return (
        <div className="rl2-section">
            <div className="rl2-header">
                <span className="rl2-header-title">
                    Recordings
                    <span className="rl2-header-count">{totalCount}</span>
                </span>
                <button type="button" className="rl2-refresh-btn"
                    onClick={() => { void loadServerItems(); void loadAssets() }}
                    disabled={isLoadingServer} title="Refresh">
                    <RefreshCw size={12} className={isLoadingServer ? 'rl2-spin' : ''} />
                </button>
            </div>

            {serverError && (
                <div className="rl2-server-error">
                    <AlertCircle size={12} />{serverError}
                    <button type="button" onClick={() => setServerError('')}><X size={10} /></button>
                </div>
            )}

            {recordings.length > 0 && (
                <div className="rl2-group">
                    <div className="rl2-group-label">
                        <span>This session</span>
                        <span className="rl2-group-count">{recordings.length}</span>
                    </div>
                    <div className="rl2-list">
                        {recordings.map(rec => (
                            <LocalRecordingRow key={rec.id}
                                rec={{ ...rec, name: localNames[rec.id] ?? rec.name }}
                                isPlaying={playingId === rec.id}
                                onPlay={() => onPlay(rec)}
                                onUpload={() => onUpload(rec.id)}
                                onDownload={() => onDownload(rec)}
                                onDelete={() => onDelete(rec.id)}
                                onRename={name => handleLocalRename(rec.id, name)}
                            />
                        ))}
                    </div>
                </div>
            )}

            {(dedupedServerItems.length > 0 || isLoadingServer) && (
                <div className="rl2-group">
                    <div className="rl2-group-label">
                        <span>Cloud storage</span>
                        {!isLoadingServer && <span className="rl2-group-count">{dedupedServerItems.length}</span>}
                    </div>
                    <div className="rl2-list">
                        {isLoadingServer && recordings.length === 0 && (
                            <div className="rl2-loading"><RefreshCw size={13} className="rl2-spin" />Loading…</div>
                        )}
                        {dedupedServerItems.map(item => (
                            <ServerRecordingRow key={item.id}
                                item={item}
                                asset={assetByUploadId[item.id]}
                                isPlaying={playingId === item.id}
                                isActionLoading={serverActionLoadingId === item.id}
                                onPlay={() => void handleServerPlay(item)}
                                onDownload={() => void handleServerDownload(item)}
                                onDelete={() => void handleServerDelete(item)}
                                onRename={name => void handleServerRename(item, name)}
                            />
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}