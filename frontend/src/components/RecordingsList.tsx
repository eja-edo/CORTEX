// RecordingsList.tsx — updated to support "View Knowledge" per asset row.
// Add import in parent (RecordPanel) and pass onViewKnowledge prop, or keep
// the knowledge view inline here. We expose it inline via a callback prop.

import { useCallback, useEffect, useRef, useState } from 'react'
import {
    Check, Clock, Download, Edit2, FileAudio, FileVideo,
    HardDrive, Monitor, MoreHorizontal, Pause, Play, RefreshCw,
    Trash2, X, AlertCircle, Zap, Radio, Brain
} from 'lucide-react'

import type { AuthRequest, Recording } from './recordingTypes'
import { ProcessAssetDialog } from './ProcessAssetDialog'

/* ─────────────────────────── Types ─────────────────────────── */

type AssetResponse = {
    id: string
    user_id: string
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

type UploadAccessUrlResponse = {
    upload_id: string
    object_key: string
    url: string
    expires_in_seconds: number
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
    activeStream?: MediaStream | null
    recordingType?: 'screen' | 'audio' | null
    /** Called when user clicks "View Knowledge" on a processed asset */
    onViewKnowledge?: (assetId: string, assetTitle: string) => void
    workspaceId?: string | null
    onAssetChange?: () => void
}

/* ─────────────────────────── Helpers ─────────────────────────── */

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

function formatDuration(seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${s.toString().padStart(2, '0')}`
}

/* ─────────────────────── Status badge ──────────────────────── */

function AssetStatusBadge({ status }: { status: string }) {
    switch (status.toUpperCase()) {
        case 'READY':
            return <span className="rl2-badge rl2-badge--ok"><Check size={10} />Ready</span>
        case 'PROCESSING':
            return <span className="rl2-badge rl2-badge--uploading"><RefreshCw size={10} className="rl2-spin" />Processing</span>
        case 'PENDING':
            return <span className="rl2-badge rl2-badge--local"><Clock size={10} />Pending</span>
        case 'ERROR':
            return <span className="rl2-badge rl2-badge--err"><AlertCircle size={10} />Error</span>
        case 'COMPLETED':
            return <span className="rl2-badge rl2-badge--ok"><Check size={10} />Completed</span>
        default:
            return <span className="rl2-badge rl2-badge--local">{status}</span>
    }
}

/* ─────────────────────── Inline edit ───────────────────────── */

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

/* ─────────────────────── Confirm delete ────────────────────── */

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

/* ─────────────────────── Context menu ──────────────────────── */

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

/* ──────────────────── Live Recording Preview Panel ─────────────────────── */

function AudioVisualiser({ stream }: { stream: MediaStream }) {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const rafRef = useRef<number>(0)

    useEffect(() => {
        const ctx = new AudioContext()
        const source = ctx.createMediaStreamSource(stream)
        const analyser = ctx.createAnalyser()
        analyser.fftSize = 64
        source.connect(analyser)

        const buf = new Uint8Array(analyser.frequencyBinCount)
        const canvas = canvasRef.current!
        const c = canvas.getContext('2d')!

        const draw = () => {
            rafRef.current = requestAnimationFrame(draw)
            analyser.getByteFrequencyData(buf)
            c.clearRect(0, 0, canvas.width, canvas.height)

            const barW = canvas.width / buf.length
            buf.forEach((v, i) => {
                const h = (v / 255) * canvas.height * 0.85
                const x = i * barW
                const grad = c.createLinearGradient(0, canvas.height, 0, canvas.height - h)
                grad.addColorStop(0, 'rgba(35,131,226,0.9)')
                grad.addColorStop(1, 'rgba(35,131,226,0.3)')
                c.fillStyle = grad
                c.beginPath()
                c.roundRect(x + 1, canvas.height - h, barW - 2, h, 2)
                c.fill()
            })
        }
        draw()
        return () => {
            cancelAnimationFrame(rafRef.current)
            void ctx.close()
        }
    }, [stream])

    return <canvas ref={canvasRef} className="rp-audio-canvas" width={480} height={80} />
}

function RecordingPreviewPanel({ stream, recordingType, elapsedSeconds }: {
    stream: MediaStream
    recordingType: 'screen' | 'audio'
    elapsedSeconds: number
}) {
    const isVideo = recordingType === 'screen'

    const videoCallbackRef = useCallback((el: HTMLVideoElement | null) => {
        if (el) el.srcObject = stream
    }, [stream])

    const elapsed = formatDuration(elapsedSeconds)

    return (
        <div className="rp-panel">
            <div className="rp-header">
                <span className="rp-live-dot" />
                <span className="rp-live-label">LIVE</span>
                <span className="rp-type-label">{isVideo ? 'Screen capture' : 'Audio capture'}</span>
                <span className="rp-elapsed">{elapsed}</span>
            </div>
            <div className="rp-preview-area">
                {isVideo ? (
                    <video ref={videoCallbackRef} className="rp-video" autoPlay muted playsInline />
                ) : (
                    <div className="rp-audio-wrap">
                        <Radio size={22} className="rp-audio-icon" />
                        <AudioVisualiser stream={stream} />
                        <span className="rp-audio-hint">Listening…</span>
                    </div>
                )}
                <div className="rp-corner-badge">
                    <span className="rp-corner-dot" />
                    REC {elapsed}
                </div>
            </div>
        </div>
    )
}

/* ──────────────────── Asset (cloud) row ───────────────────── */

function AssetRow({ asset, isPlaying, isActionLoading, onPlay, onDownload, onDelete, onRename, onProcess, onViewKnowledge }: {
    asset: AssetResponse
    isPlaying: boolean
    isActionLoading: boolean
    onPlay: () => void
    onDownload: () => void
    onDelete: () => void
    onRename: (name: string) => void
    onProcess: () => void
    onViewKnowledge?: () => void
}) {
    const [isEditing, setIsEditing] = useState(false)
    const [menuOpen, setMenuOpen] = useState(false)
    const [confirmDelete, setConfirmDelete] = useState(false)

    const displayName = asset.title || asset.source_object_key.split('/').pop() || asset.id
    const canProcess = asset.status.toUpperCase() === 'READY'
    const isAudio = asset.type?.toLowerCase().includes('audio')
    // Knowledge is available when status is READY (processed)
    const hasKnowledge = asset.status.toUpperCase() === 'COMPLETED'

    const menuItems = [
        { label: 'Rename', icon: <Edit2 size={12} />, onClick: () => setIsEditing(true) },
        { label: 'Download', icon: <Download size={12} />, onClick: onDownload },
        { label: 'Process with AI', icon: <Zap size={12} />, disabled: !canProcess, onClick: onProcess },
        { label: 'View Knowledge', icon: <Brain size={12} />, disabled: !hasKnowledge || !onViewKnowledge, onClick: () => onViewKnowledge?.() },
        { label: 'Delete', icon: <Trash2 size={12} />, danger: true, onClick: () => setConfirmDelete(true) },
    ]

    return (
        <>
            <div className={`rl2-row ${isPlaying ? 'rl2-row--playing' : ''} ${isActionLoading ? 'rl2-row--loading' : ''}`}>
                <button type="button" className={`rl2-play-btn ${isPlaying ? 'rl2-play-btn--active' : ''}`} onClick={onPlay} disabled={isActionLoading}>
                    {isActionLoading
                        ? <RefreshCw size={14} className="rl2-spin" />
                        : isPlaying
                            ? <Pause size={14} />
                            : isAudio ? <FileAudio size={14} /> : <FileVideo size={14} />}
                </button>

                <div className="rl2-info">
                    {isEditing
                        ? <InlineEdit value={displayName} onSave={v => { onRename(v); setIsEditing(false) }} onCancel={() => setIsEditing(false)} />
                        : <div className="rl2-name" onDoubleClick={() => setIsEditing(true)}>{displayName}</div>}

                    <div className="rl2-meta">
                        <AssetStatusBadge status={asset.status} />
                        {(asset.metadata as Record<string, unknown>)?.size && (
                            <span><HardDrive size={9} />{formatFileSize((asset.metadata as Record<string, unknown>).size as number)}</span>
                        )}
                        <span><Clock size={9} />{formatRelativeTime(asset.created_at)}</span>
                    </div>

                    {asset.description && <div className="rl2-asset-desc">{asset.description}</div>}
                </div>

                <div className="rl2-actions">
                    <button type="button" className={`rl2-action-btn ${isPlaying ? 'active' : ''}`} onClick={onPlay} disabled={isActionLoading}>
                        {isPlaying ? <Pause size={12} /> : <Play size={12} />}
                    </button>
                    {canProcess && (
                        <button type="button" className="rl2-action-btn" onClick={onProcess} disabled={isActionLoading} title="Process with AI">
                            <Zap size={12} />
                        </button>
                    )}
                    {/* Knowledge button — shown when asset has been processed */}
                    {hasKnowledge && onViewKnowledge && (
                        <button
                            type="button"
                            className="rl2-action-btn rl2-action-btn--knowledge"
                            onClick={onViewKnowledge}
                            disabled={isActionLoading}
                            title="View Knowledge Summary"
                        >
                            <Brain size={12} />
                        </button>
                    )}
                    <button type="button" className="rl2-action-btn" onClick={onDownload} disabled={isActionLoading} title="Download">
                        <Download size={12} />
                    </button>
                    <div className="rl2-menu-wrap">
                        <button type="button" className={`rl2-action-btn ${menuOpen ? 'active' : ''}`} onClick={() => setMenuOpen(v => !v)}>
                            <MoreHorizontal size={12} />
                        </button>
                        {menuOpen && <ContextMenu items={menuItems} onClose={() => setMenuOpen(false)} />}
                    </div>
                </div>
            </div>

            {confirmDelete && (
                <ConfirmDelete
                    name={displayName}
                    onConfirm={() => { setConfirmDelete(false); onDelete() }}
                    onCancel={() => setConfirmDelete(false)}
                />
            )}
        </>
    )
}

/* ──────────────────── Main component ──────────────────────── */

export function RecordingsList({
    requestWithAuth, recordings, playingId,
    onPlayServerVideo, onPlayServerAudio,
    activeStream, recordingType,
    onViewKnowledge, workspaceId, onAssetChange,
}: RecordingsListProps) {
    const [assets, setAssets] = useState<AssetResponse[]>([])
    const [isLoadingAssets, setIsLoadingAssets] = useState(false)
    const [assetError, setAssetError] = useState('')
    const [actionLoadingId, setActionLoadingId] = useState<string | null>(null)
    const [pendingProcessAssetId, setPendingProcessAssetId] = useState<string | null>(null)
    const [isProcessing, setIsProcessing] = useState(false)
    const promptedAssetIds = useRef<Set<string>>(new Set())

    const [elapsedSeconds, setElapsedSeconds] = useState(0)
    const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

    const isRecording = Boolean(activeStream && recordingType)

    useEffect(() => {
        if (isRecording) {
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setElapsedSeconds(0)
            timerRef.current = setInterval(() => setElapsedSeconds((s: number) => s + 1), 1000)
        } else {
            if (timerRef.current) clearInterval(timerRef.current)
            setElapsedSeconds(0)
        }
        return () => { if (timerRef.current) clearInterval(timerRef.current) }
    }, [isRecording])

    const loadAssets = useCallback(async () => {
        setIsLoadingAssets(true)
        setAssetError('')
        try {
            const url = workspaceId 
                ? `/assets/workspaces/${workspaceId}` 
                : '/assets?limit=200&offset=0'
            const list = await requestWithAuth<AssetResponse[]>(url)
            list.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
            setAssets(list)
        } catch (err) {
            setAssetError(err instanceof Error ? err.message : 'Cannot load recordings from server')
        } finally {
            setIsLoadingAssets(false)
        }
    }, [requestWithAuth, workspaceId])

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void loadAssets()
    }, [loadAssets])

    useEffect(() => {
        const hasNewUpload = recordings.some(r => r.uploadState === 'uploaded')
        if (hasNewUpload) {
            // eslint-disable-next-line react-hooks/set-state-in-effect
            void loadAssets()
            onAssetChange?.()
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [recordings])

    useEffect(() => {
        for (const rec of recordings) {
            if (
                rec.uploadState === 'uploaded' &&
                rec.uploadedAssetId &&
                !promptedAssetIds.current.has(rec.uploadedAssetId)
            ) {
                promptedAssetIds.current.add(rec.uploadedAssetId)
                setPendingProcessAssetId(rec.uploadedAssetId)
                break
            }
        }
    }, [recordings])

    const getAccessUrl = useCallback(async (asset: AssetResponse, disposition: 'inline' | 'attachment') => {
        if (!asset.source_upload_id) throw new Error('No upload ID on asset')
        const resp = await requestWithAuth<UploadAccessUrlResponse>(
            `/upload/access?upload_id=${asset.source_upload_id}&disposition=${disposition}`,
            { method: 'GET' }
        )
        return resp.url
    }, [requestWithAuth])

    const handlePlay = useCallback(async (asset: AssetResponse) => {
        setActionLoadingId(asset.id)
        setAssetError('')
        try {
            const url = await getAccessUrl(asset, 'inline')
            const name = asset.title || asset.id
            const isAudio = asset.type?.toLowerCase().includes('audio')
            if (isAudio) onPlayServerAudio({ id: asset.id, name, url })
            else onPlayServerVideo({ id: asset.id, name, url })
        } catch (err) {
            setAssetError(err instanceof Error ? err.message : 'Cannot play media')
        } finally {
            setActionLoadingId(null)
        }
    }, [getAccessUrl, onPlayServerVideo, onPlayServerAudio])

    const handleDownload = useCallback(async (asset: AssetResponse) => {
        setActionLoadingId(asset.id)
        setAssetError('')
        try {
            const url = await getAccessUrl(asset, 'attachment')
            const name = asset.title || asset.id
            const a = document.createElement('a')
            a.href = url; a.download = name; a.target = '_blank'; a.rel = 'noreferrer noopener'; a.click()
        } catch (err) {
            setAssetError(err instanceof Error ? err.message : 'Cannot download media')
        } finally {
            setActionLoadingId(null)
        }
    }, [getAccessUrl])

    const handleDelete = useCallback(async (asset: AssetResponse) => {
        setAssetError('')
        try {
            await requestWithAuth(`/assets/${asset.id}`, { method: 'DELETE' })
            setAssets(prev => prev.filter(a => a.id !== asset.id))
            onAssetChange?.()
        } catch (err) {
            setAssetError(err instanceof Error ? err.message : 'Cannot delete recording')
        }
    }, [requestWithAuth, onAssetChange])

    const handleRename = useCallback(async (asset: AssetResponse, newTitle: string) => {
        setAssetError('')
        try {
            const updated = await requestWithAuth<AssetResponse>(`/assets/${asset.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: newTitle }),
            })
            setAssets(prev => prev.map(a => a.id === asset.id ? updated : a))
            onAssetChange?.()
        } catch (err) {
            setAssetError(err instanceof Error ? err.message : 'Cannot rename recording')
        }
    }, [requestWithAuth, onAssetChange])

    const handleProcess = useCallback((asset: AssetResponse) => {
        setPendingProcessAssetId(asset.id)
    }, [])

    const handleProcessConfirm = useCallback(async () => {
        if (!pendingProcessAssetId) return
        setIsProcessing(true)
        try {
            await requestWithAuth(`/assets/${pendingProcessAssetId}/process`, { method: 'POST' })
            setPendingProcessAssetId(null)
            setTimeout(() => {
                void loadAssets()
                onAssetChange?.()
            }, 1000)
        } catch (err) {
            setAssetError(err instanceof Error ? err.message : 'Cannot start processing')
        } finally {
            setIsProcessing(false)
        }
    }, [pendingProcessAssetId, requestWithAuth, loadAssets, onAssetChange])


    const pendingAssetTitle = pendingProcessAssetId
        ? (assets.find(a => a.id === pendingProcessAssetId)?.title ?? 'Recording')
        : ''

    const totalCount = recordings.length + assets.length

    if (totalCount === 0 && !isLoadingAssets && !isRecording) {
        return (
            <div className="rl2-empty">
                <div className="rl2-empty-icon"><Monitor size={28} /></div>
                <div className="rl2-empty-title">No recordings yet</div>
                <div className="rl2-empty-sub">Start screen recording or audio capture above</div>
            </div>
        )
    }

    return (
        <>
            {isRecording && activeStream && recordingType && (
                <RecordingPreviewPanel
                    stream={activeStream}
                    recordingType={recordingType}
                    elapsedSeconds={elapsedSeconds}
                />
            )}

            <div className="rl2-section">
                <div className="rl2-header">
                    <span className="rl2-header-title">
                        Recordings
                        <span className="rl2-header-count">{totalCount}</span>
                    </span>
                    <button type="button" className="rl2-refresh-btn"
                        onClick={() => void loadAssets()}
                        disabled={isLoadingAssets} title="Refresh">
                        <RefreshCw size={12} className={isLoadingAssets ? 'rl2-spin' : ''} />
                    </button>
                </div>

                {assetError && (
                    <div className="rl2-server-error">
                        <AlertCircle size={12} />{assetError}
                        <button type="button" onClick={() => setAssetError('')}><X size={10} /></button>
                    </div>
                )}

                {(assets.length > 0 || isLoadingAssets) && (
                    <div className="rl2-group">
                        <div className="rl2-group-label">
                            <span>Cloud storage</span>
                            {!isLoadingAssets && <span className="rl2-group-count">{assets.length}</span>}
                        </div>
                        <div className="rl2-list">
                            {isLoadingAssets && (
                                <div className="rl2-loading">
                                    <RefreshCw size={13} className="rl2-spin" />Loading…
                                </div>
                            )}
                            {assets.map(asset => (
                                <AssetRow key={asset.id}
                                    asset={asset}
                                    isPlaying={playingId === asset.id}
                                    isActionLoading={actionLoadingId === asset.id}
                                    onPlay={() => void handlePlay(asset)}
                                    onDownload={() => void handleDownload(asset)}
                                    onDelete={() => void handleDelete(asset)}
                                    onRename={name => void handleRename(asset, name)}
                                    onProcess={() => handleProcess(asset)}
                                    onViewKnowledge={
                                        onViewKnowledge
                                            ? () => onViewKnowledge(asset.id, asset.title || asset.id)
                                            : undefined
                                    }
                                />
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {pendingProcessAssetId && (
                <ProcessAssetDialog
                    assetTitle={pendingAssetTitle}
                    isLoading={isProcessing}
                    onProcess={handleProcessConfirm}
                    onSkip={() => setPendingProcessAssetId(null)}
                />
            )}
        </>
    )
}