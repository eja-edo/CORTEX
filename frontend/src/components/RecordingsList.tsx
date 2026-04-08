import { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, Mic, Monitor, Play, Square, Trash2, Upload } from 'lucide-react'

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

function fallbackName(item: UploadListItem): string {
    if (item.filename && item.filename.trim().length > 0) return item.filename
    const parts = item.object_key.split('/')
    return parts[parts.length - 1] || item.object_key
}

export function RecordingsList({
    requestWithAuth,
    recordings,
    playingId,
    onPlay,
    onPlayServerVideo,
    onPlayServerAudio,
    onUpload,
    onDownload,
    onDelete,
}: RecordingsListProps) {
    const [serverItems, setServerItems] = useState<UploadListItem[]>([])
    const [isLoadingServer, setIsLoadingServer] = useState(false)
    const [serverError, setServerError] = useState<string>('')
    const [serverActionLoadingId, setServerActionLoadingId] = useState<string | null>(null)

    const getServerAccessUrl = useCallback(async (item: UploadListItem, disposition: 'inline' | 'attachment') => {
        const response = await requestWithAuth<UploadAccessUrlResponse>(
            `/upload/access?upload_id=${item.id}&disposition=${disposition}`,
            { method: 'GET' },
        )
        return response.url
    }, [requestWithAuth])

    const loadServerItems = useCallback(async () => {
        setIsLoadingServer(true)
        setServerError('')
        try {
            const response = await requestWithAuth<UploadListResponse>('/upload/list?limit=100&offset=0', {
                method: 'GET',
            })
            setServerItems(response.items)
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Không thể tải danh sách record từ server'
            setServerError(message)
        } finally {
            setIsLoadingServer(false)
        }
    }, [requestWithAuth])

    useEffect(() => {
        void loadServerItems()
    }, [loadServerItems])

    useEffect(() => {
        if (recordings.length === 0) return
        void loadServerItems()
    }, [recordings, loadServerItems])

    const localUploadedKeys = useMemo(() => {
        return new Set(
            recordings
                .map((rec) => rec.uploadedObjectKey)
                .filter((key): key is string => Boolean(key)),
        )
    }, [recordings])

    const dedupedServerItems = useMemo(
        () => serverItems.filter((item) => !localUploadedKeys.has(item.object_key)),
        [localUploadedKeys, serverItems],
    )

    const totalCount = recordings.length + dedupedServerItems.length

    const handleServerPlay = useCallback(async (item: UploadListItem) => {
        setServerActionLoadingId(item.id)
        setServerError('')
        try {
            const accessUrl = await getServerAccessUrl(item, 'inline')
            if (item.media_type === 'video') {
                onPlayServerVideo({
                    id: item.id,
                    name: fallbackName(item),
                    url: accessUrl,
                })
            } else {
                onPlayServerAudio({
                    id: item.id,
                    name: fallbackName(item),
                    url: accessUrl,
                })
            }
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Không thể mở media từ server'
            setServerError(message)
        } finally {
            setServerActionLoadingId(null)
        }
    }, [getServerAccessUrl, onPlayServerAudio, onPlayServerVideo])

    const handleServerDownload = useCallback(async (item: UploadListItem) => {
        setServerActionLoadingId(item.id)
        setServerError('')
        try {
            const accessUrl = await getServerAccessUrl(item, 'attachment')
            const a = document.createElement('a')
            a.href = accessUrl
            a.download = fallbackName(item)
            a.target = '_blank'
            a.rel = 'noreferrer noopener'
            a.click()
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Không thể tải media từ server'
            setServerError(message)
        } finally {
            setServerActionLoadingId(null)
        }
    }, [getServerAccessUrl])

    if (totalCount === 0 && !isLoadingServer) {
        return (
            <div className="record-empty">
                <p>Chưa có recording nào. Bắt đầu quay màn hình hoặc ghi âm.</p>
            </div>
        )
    }

    return (
        <div className="record-list-section">
            <div className="record-list-header">Recordings ({totalCount})</div>
            {serverError && <div className="record-list-meta">{serverError}</div>}
            <div className="record-list">
                {recordings.map((rec) => (
                    <div key={rec.id} className="record-list-item">
                        <div className="record-list-icon">
                            {rec.type === 'audio' ? <Mic size={13} /> : <Monitor size={13} />}
                        </div>
                        <div className="record-list-info">
                            <div className="record-list-name">{rec.name}</div>
                            <div className="record-list-meta">
                                {formatDuration(rec.duration)} · {rec.type === 'audio' ? 'audio' : 'video'}
                                {rec.uploadState === 'uploading' ? ` · uploading ${rec.uploadProgress}%` : ''}
                                {rec.uploadState === 'uploaded' ? ' · uploaded' : ''}
                                {rec.uploadState === 'failed' ? ' · upload failed' : ''}
                            </div>
                            {rec.uploadError && <div className="record-list-meta">{rec.uploadError}</div>}
                        </div>
                        <div className="record-list-actions">
                            <button
                                type="button"
                                className={`record-action-btn ${playingId === rec.id ? 'active' : ''}`}
                                onClick={() => onPlay(rec)}
                                aria-label={playingId === rec.id ? 'Dừng' : 'Phát'}
                            >
                                {playingId === rec.id ? <Square size={12} /> : <Play size={12} />}
                            </button>
                            <button
                                type="button"
                                className={`record-action-btn ${rec.uploadState === 'uploaded' ? 'active' : ''}`}
                                onClick={() => onUpload(rec.id)}
                                aria-label={rec.uploadState === 'uploaded' ? 'Đã upload' : 'Upload'}
                                disabled={rec.uploadState === 'uploading' || rec.uploadState === 'uploaded'}
                                title={rec.uploadState === 'uploaded' ? 'Uploaded' : 'Upload to cloud'}
                            >
                                <Upload size={12} />
                            </button>
                            <button
                                type="button"
                                className="record-action-btn"
                                onClick={() => onDownload(rec)}
                                aria-label="Tải xuống"
                            >
                                <Download size={12} />
                            </button>
                            <button
                                type="button"
                                className="record-action-btn record-action-btn--danger"
                                onClick={() => onDelete(rec.id)}
                                aria-label="Xoá"
                            >
                                <Trash2 size={12} />
                            </button>
                        </div>
                    </div>
                ))}

                {dedupedServerItems.map((rec) => (
                    <div key={rec.id} className="record-list-item">
                        <div className="record-list-icon">
                            {rec.media_type === 'audio' ? <Mic size={13} /> : <Monitor size={13} />}
                        </div>
                        <div className="record-list-info">
                            <div className="record-list-name">{fallbackName(rec)}</div>
                            <div className="record-list-meta">
                                {rec.media_type === 'audio' ? 'audio' : 'video'} · uploaded · {Math.max(1, Math.round(rec.total_size / 1024 / 1024))} MB
                            </div>

                        </div>
                        <div className="record-list-actions">
                            <button
                                type="button"
                                className={`record-action-btn ${playingId === rec.id ? 'active' : ''}`}
                                onClick={() => void handleServerPlay(rec)}
                                aria-label={playingId === rec.id ? 'Dừng' : 'Phát'}
                                disabled={serverActionLoadingId === rec.id}
                            >
                                {playingId === rec.id ? <Square size={12} /> : <Play size={12} />}
                            </button>
                            <button
                                type="button"
                                className="record-action-btn active"
                                aria-label="Uploaded"
                                disabled
                                title="Uploaded"
                            >
                                <Upload size={12} />
                            </button>
                            <button
                                type="button"
                                className="record-action-btn"
                                onClick={() => void handleServerDownload(rec)}
                                aria-label="Tải xuống"
                                disabled={serverActionLoadingId === rec.id}
                            >
                                <Download size={12} />
                            </button>
                            <button
                                type="button"
                                className="record-action-btn record-action-btn--danger"
                                onClick={() => onDelete(rec.id)}
                                aria-label="Xoá"
                            >
                                <Trash2 size={12} />
                            </button>
                        </div>
                    </div>
                ))}

                {isLoadingServer && <div className="record-list-meta">Đang tải danh sách từ server...</div>}
            </div>
        </div>
    )
}
