// RecordPanel.tsx — screen/audio recording panel.
// Knowledge view is now handled as a workspace route (/assets/:assetId/knowledge)

import { useCallback, useEffect, useRef, useState } from 'react'
import { Mic, MicOff, Monitor, Video, VideoOff } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { RecordingsList } from './RecordingsList'
import type { AuthRequest, Recording } from './recordingTypes'

type UploadInitResponse = {
    upload_id: string
    object_key: string
    total_parts: number
    expires_in_seconds: number
}

type UploadPresignedResponse = {
    upload_id: string
    part_number: number
    url: string
    expires_in_seconds: number
}

type UploadSessionResponse = {
    id: string
    status: 'initiated' | 'uploading' | 'completed' | 'failed'
    object_key: string
    total_parts: number
    total_size: number
    uploaded_parts: number[]
    created_at: string
    updated_at: string
    completed_at: string | null
}

type UploadCompleteResponse = {
    upload_id: string
    asset_id: string
    object_key: string
    status: 'initiated' | 'uploading' | 'completed' | 'failed'
}

type LiveUploadContext = {
    uploadId: string
    objectKey: string
    nextPartNumber: number
    bufferedChunks: Blob[]
    bufferedBytes: number
    flushChain: Promise<void>
    lastError?: string
}

type RecordPanelProps = {
    requestWithAuth: AuthRequest
    isVisible: boolean
    initialAssetId?: string | null
    onAssetViewed?: () => void
    workspaceId?: string | null
    onAssetChange?: () => void
}

const MIN_PART_SIZE = 5 * 1024 * 1024
const UPLOAD_CONCURRENCY = 4

function formatDuration(seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${s.toString().padStart(2, '0')}`
}

function formatDate(date: Date): string {
    return date.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' }) +
        ' ' + date.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
}

export function RecordPanel({ requestWithAuth, isVisible, workspaceId, onAssetChange }: RecordPanelProps) {
    const navigate = useNavigate()
    const [recordings, setRecordings] = useState<Recording[]>([])
    const [isRecordingAudio, setIsRecordingAudio] = useState(false)
    const [isRecordingScreen, setIsRecordingScreen] = useState(false)
    const [audioDuration, setAudioDuration] = useState(0)
    const [screenDuration, setScreenDuration] = useState(0)
    const [playingId, setPlayingId] = useState<string | null>(null)
    const [activeVideoId, setActiveVideoId] = useState<string | null>(null)
    const [activeVideoLabel, setActiveVideoLabel] = useState<string>('')
    const [activeAudioId, setActiveAudioId] = useState<string | null>(null)
    const [activeAudioLabel, setActiveAudioLabel] = useState<string>('')
    const [error, setError] = useState<string>('')

    const [activeStream, setActiveStream] = useState<MediaStream | null>(null)
    const [recordingType, setRecordingType] = useState<'screen' | 'audio' | null>(null)

    const audioRecorderRef = useRef<MediaRecorder | null>(null)
    const screenRecorderRef = useRef<MediaRecorder | null>(null)
    const audioChunksRef = useRef<Blob[]>([])
    const screenChunksRef = useRef<Blob[]>([])
    const audioTimerRef = useRef<number | null>(null)
    const screenTimerRef = useRef<number | null>(null)
    const videoElRef = useRef<HTMLVideoElement | null>(null)
    const audioElRef = useRef<HTMLAudioElement | null>(null)
    const audioStreamRef = useRef<MediaStream | null>(null)
    const screenStreamRef = useRef<MediaStream | null>(null)
    const audioDurationRef = useRef(0)
    const screenDurationRef = useRef(0)
    const recordingsRef = useRef<Recording[]>([])
    const audioLiveUploadRef = useRef<LiveUploadContext | null>(null)
    const screenLiveUploadRef = useRef<LiveUploadContext | null>(null)

    useEffect(() => { recordingsRef.current = recordings }, [recordings])
    useEffect(() => { audioDurationRef.current = audioDuration }, [audioDuration])
    useEffect(() => { screenDurationRef.current = screenDuration }, [screenDuration])

    useEffect(() => {
        return () => {
            if (audioTimerRef.current) clearInterval(audioTimerRef.current)
            if (screenTimerRef.current) clearInterval(screenTimerRef.current)
            audioStreamRef.current?.getTracks().forEach(t => t.stop())
            screenStreamRef.current?.getTracks().forEach(t => t.stop())
            audioElRef.current?.pause()
            videoElRef.current?.pause()
            recordings.forEach(r => URL.revokeObjectURL(r.url))
        }
    }, [])

    const startAudioRecording = useCallback(async () => {
        setError('')
        try {
            const liveCtx = await initLiveUpload('audio-live', 'audio/webm')
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
            audioStreamRef.current = stream
            audioLiveUploadRef.current = liveCtx
            setActiveStream(stream)
            setRecordingType('audio')
            const recorder = new MediaRecorder(stream)
            audioRecorderRef.current = recorder
            audioChunksRef.current = []
            recorder.ondataavailable = e => {
                if (e.data.size > 0) {
                    audioChunksRef.current.push(e.data)
                    appendLiveChunk(audioLiveUploadRef.current, e.data)
                }
            }
            recorder.onstop = async () => {
                const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
                const url = URL.createObjectURL(blob)
                const dur = audioDurationRef.current
                const finalize = await finalizeLiveUpload(audioLiveUploadRef.current, blob.size)
                const newRec: Recording = {
                    id: Date.now().toString(),
                    type: 'audio',
                    name: `Ghi âm ${formatDate(new Date())}`,
                    blob, url,
                    duration: dur,
                    createdAt: new Date(),
                    uploadState: finalize.status,
                    uploadProgress: finalize.status === 'uploaded' ? 100 : 0,
                    uploadedObjectKey: finalize.objectKey,
                    uploadedAssetId: finalize.assetId,
                    uploadError: finalize.error,
                }
                setRecordings(prev => [newRec, ...prev])
                setAudioDuration(0)
                audioDurationRef.current = 0
                audioLiveUploadRef.current = null
                stream.getTracks().forEach(t => t.stop())
                audioStreamRef.current = null
                setActiveStream(null)
                setRecordingType(null)
            }
            recorder.start(200)
            setIsRecordingAudio(true)
            audioTimerRef.current = window.setInterval(() => setAudioDuration(d => d + 1), 1000)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Không thể truy cập microphone. Hãy cho phép quyền truy cập.')
            audioLiveUploadRef.current = null
            setActiveStream(null)
            setRecordingType(null)
        }
    }, [])

    const stopAudioRecording = useCallback(() => {
        if (audioTimerRef.current) { clearInterval(audioTimerRef.current); audioTimerRef.current = null }
        audioRecorderRef.current?.stop()
        setIsRecordingAudio(false)
    }, [])

    const startScreenRecording = useCallback(async () => {
        setError('')
        try {
            const liveCtx = await initLiveUpload('screen-live', 'video/webm')
            const stream = await navigator.mediaDevices.getDisplayMedia({
                video: true,
                audio: true,
            })
            screenStreamRef.current = stream
            screenLiveUploadRef.current = liveCtx
            setActiveStream(stream)
            setRecordingType('screen')
            const recorder = new MediaRecorder(stream)
            screenRecorderRef.current = recorder
            screenChunksRef.current = []
            recorder.ondataavailable = e => {
                if (e.data.size > 0) {
                    screenChunksRef.current.push(e.data)
                    appendLiveChunk(screenLiveUploadRef.current, e.data)
                }
            }
            recorder.onstop = async () => {
                const blob = new Blob(screenChunksRef.current, { type: 'video/webm' })
                const url = URL.createObjectURL(blob)
                const dur = screenDurationRef.current
                const finalize = await finalizeLiveUpload(screenLiveUploadRef.current, blob.size)
                const newRec: Recording = {
                    id: Date.now().toString(),
                    type: 'video',
                    name: `Màn hình ${formatDate(new Date())}`,
                    blob, url,
                    duration: dur,
                    createdAt: new Date(),
                    uploadState: finalize.status,
                    uploadProgress: finalize.status === 'uploaded' ? 100 : 0,
                    uploadedObjectKey: finalize.objectKey,
                    uploadedAssetId: finalize.assetId,
                    uploadError: finalize.error,
                }
                setRecordings(prev => [newRec, ...prev])
                setScreenDuration(0)
                screenDurationRef.current = 0
                screenLiveUploadRef.current = null
                stream.getTracks().forEach(t => t.stop())
                screenStreamRef.current = null
                setActiveStream(null)
                setRecordingType(null)
            }
            stream.getVideoTracks()[0].onended = () => { stopScreenRecording() }
            recorder.start(200)
            setIsRecordingScreen(true)
            screenTimerRef.current = window.setInterval(() => setScreenDuration(d => d + 1), 1000)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Không thể bắt đầu quay màn hình.')
            screenLiveUploadRef.current = null
            setActiveStream(null)
            setRecordingType(null)
        }
    }, [])

    const stopScreenRecording = useCallback(() => {
        if (screenTimerRef.current) { clearInterval(screenTimerRef.current); screenTimerRef.current = null }
        screenRecorderRef.current?.stop()
        setIsRecordingScreen(false)
    }, [])

    const handlePlay = useCallback((rec: Recording) => {
        if (rec.type === 'audio') {
            if (playingId === rec.id) {
                audioElRef.current?.pause()
                setPlayingId(null)
                setActiveAudioId(null)
                setActiveAudioLabel('')
                return
            }
            videoElRef.current?.pause()
            setActiveVideoId(null)
            setActiveVideoLabel('')
            setPlayingId(rec.id)
            setActiveAudioId(rec.id)
            setActiveAudioLabel(rec.name)
            window.requestAnimationFrame(() => {
                if (audioElRef.current) {
                    audioElRef.current.src = rec.url
                    void audioElRef.current.play()
                    audioElRef.current.onended = () => {
                        setPlayingId(null)
                        setActiveAudioId(null)
                        setActiveAudioLabel('')
                    }
                }
            })
        } else {
            if (playingId === rec.id) {
                videoElRef.current?.pause()
                setPlayingId(null)
                setActiveVideoId(null)
                setActiveVideoLabel('')
                return
            }
            audioElRef.current?.pause()
            setActiveAudioId(null)
            setActiveAudioLabel('')
            setActiveVideoId(rec.id)
            setActiveVideoLabel(rec.name)
            setPlayingId(rec.id)
            window.requestAnimationFrame(() => {
                if (videoElRef.current) {
                    videoElRef.current.src = rec.url
                    videoElRef.current.play()
                    videoElRef.current.onended = () => setPlayingId(null)
                }
            })
        }
    }, [playingId])

    const handlePlayServerVideo = useCallback((params: { id: string; name: string; url: string }) => {
        if (playingId === params.id) {
            videoElRef.current?.pause()
            setPlayingId(null)
            setActiveVideoId(null)
            setActiveVideoLabel('')
            return
        }
        audioElRef.current?.pause()
        setActiveAudioId(null)
        setActiveAudioLabel('')
        setActiveVideoId(params.id)
        setActiveVideoLabel(params.name)
        setPlayingId(params.id)
        window.requestAnimationFrame(() => {
            if (videoElRef.current) {
                videoElRef.current.src = params.url
                void videoElRef.current.play()
                videoElRef.current.onended = () => {
                    setPlayingId(null)
                    setActiveVideoId(null)
                    setActiveVideoLabel('')
                }
            }
        })
    }, [playingId])

    const handlePlayServerAudio = useCallback((params: { id: string; name: string; url: string }) => {
        if (playingId === params.id) {
            audioElRef.current?.pause()
            setPlayingId(null)
            setActiveAudioId(null)
            setActiveAudioLabel('')
            return
        }
        videoElRef.current?.pause()
        setActiveVideoId(null)
        setActiveVideoLabel('')
        setActiveAudioId(params.id)
        setActiveAudioLabel(params.name)
        setPlayingId(params.id)
        window.requestAnimationFrame(() => {
            if (audioElRef.current) {
                audioElRef.current.src = params.url
                void audioElRef.current.play()
                audioElRef.current.onended = () => {
                    setPlayingId(null)
                    setActiveAudioId(null)
                    setActiveAudioLabel('')
                }
            }
        })
    }, [playingId])

    const handleDownload = useCallback((rec: Recording) => {
        const a = document.createElement('a')
        a.href = rec.url
        a.download = rec.name + (rec.type === 'audio' ? '.webm' : '.webm')
        a.click()
    }, [])

    const handleDelete = useCallback((id: string) => {
        if (playingId === id) {
            videoElRef.current?.pause()
            audioElRef.current?.pause()
            setPlayingId(null)
        }
        if (activeVideoId === id) {
            setActiveVideoId(null)
            setActiveVideoLabel('')
            if (videoElRef.current) videoElRef.current.src = ''
        }
        if (activeAudioId === id) {
            setActiveAudioId(null)
            setActiveAudioLabel('')
            if (audioElRef.current) audioElRef.current.src = ''
        }
        setRecordings(prev => {
            const rec = prev.find(r => r.id === id)
            if (rec) URL.revokeObjectURL(rec.url)
            return prev.filter(r => r.id !== id)
        })
    }, [activeAudioId, activeVideoId, playingId])

    const hasVideos = recordings.some(r => r.type === 'video') || Boolean(activeVideoId)
    const hasAudioPreview = Boolean(activeAudioId)

    const updateRecording = useCallback((id: string, updater: (rec: Recording) => Recording) => {
        setRecordings(prev => prev.map(rec => (rec.id === id ? updater(rec) : rec)))
    }, [])

    const splitBlobIntoParts = useCallback((blob: Blob) => {
        const chunks: Array<{ partNumber: number; chunk: Blob }> = []
        let offset = 0
        let partNumber = 1
        while (offset < blob.size) {
            const end = Math.min(offset + MIN_PART_SIZE, blob.size)
            chunks.push({ partNumber, chunk: blob.slice(offset, end, blob.type || 'video/webm') })
            partNumber += 1
            offset = end
        }
        return chunks
    }, [])

    const uploadPartWithRetry = useCallback(async (
        uploadId: string,
        partNumber: number,
        chunk: Blob,
        isLastPart: boolean,
    ) => {
        const tryOnce = async () => {
            const signed = await requestWithAuth<UploadPresignedResponse>(
                `/upload/presigned?upload_id=${uploadId}&part_number=${partNumber}`,
                { method: 'GET' },
            )
            const putResponse = await fetch(signed.url, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/octet-stream' },
                body: chunk,
            })
            if (!putResponse.ok) throw new Error(`Upload part ${partNumber} failed (${putResponse.status})`)
            const etag = putResponse.headers.get('ETag')
            if (!etag) throw new Error(`Missing ETag for part ${partNumber}`)
            await requestWithAuth('/upload/part/confirm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ upload_id: uploadId, part_number: partNumber, etag, size: chunk.size, is_last_part: isLastPart }),
            })
        }
        try { await tryOnce() } catch { await tryOnce() }
    }, [requestWithAuth])

    const initLiveUpload = useCallback(async (filenamePrefix: string, contentType: string) => {
        const initPayload = await requestWithAuth<UploadInitResponse>('/upload/init', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filename: `${filenamePrefix}-${Date.now()}.webm`,
                content_type: contentType || 'video/webm',
                total_parts: 0,
                total_size: 0,
            }),
        })
        const context: LiveUploadContext = {
            uploadId: initPayload.upload_id,
            objectKey: initPayload.object_key,
            nextPartNumber: 1,
            bufferedChunks: [],
            bufferedBytes: 0,
            flushChain: Promise.resolve(),
        }
        return context
    }, [requestWithAuth])

    const enqueueBufferedUpload = useCallback((ctx: LiveUploadContext, flushLast: boolean) => {
        const run = async () => {
            while (ctx.bufferedBytes >= MIN_PART_SIZE || (flushLast && ctx.bufferedBytes > 0)) {
                const blob = new Blob(ctx.bufferedChunks, { type: 'video/webm' })
                const partNumber = ctx.nextPartNumber
                const isLastPart = flushLast
                ctx.nextPartNumber += 1
                ctx.bufferedChunks = []
                ctx.bufferedBytes = 0
                await uploadPartWithRetry(ctx.uploadId, partNumber, blob, isLastPart)
            }
        }
        ctx.flushChain = ctx.flushChain.then(run).catch((err) => {
            ctx.lastError = err instanceof Error ? err.message : 'Upload chunk failed'
            throw err
        })
        return ctx.flushChain
    }, [uploadPartWithRetry])

    const appendLiveChunk = useCallback((ctx: LiveUploadContext | null, chunk: Blob) => {
        if (!ctx || chunk.size === 0) return
        ctx.bufferedChunks.push(chunk)
        ctx.bufferedBytes += chunk.size
        if (ctx.bufferedBytes >= MIN_PART_SIZE) void enqueueBufferedUpload(ctx, false)
    }, [enqueueBufferedUpload])

    const finalizeLiveUpload = useCallback(async (ctx: LiveUploadContext | null, totalSize: number) => {
        if (!ctx) return { status: 'failed' as const, objectKey: undefined, assetId: undefined, error: 'Missing upload context' }
        try {
            await enqueueBufferedUpload(ctx, true)
            const uploadedParts = ctx.nextPartNumber - 1
            if (uploadedParts <= 0) return { status: 'failed' as const, objectKey: undefined, assetId: undefined, error: 'No data uploaded' }
            const complete = await requestWithAuth<UploadCompleteResponse>('/upload/complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ upload_id: ctx.uploadId, total_parts: uploadedParts, total_size: totalSize }),
            })
            return { status: 'uploaded' as const, objectKey: complete.object_key, assetId: complete.asset_id, error: undefined }
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Live upload failed'
            return { status: 'failed' as const, objectKey: undefined, assetId: undefined, error: message }
        }
    }, [enqueueBufferedUpload, requestWithAuth])

    const handleUpload = useCallback(async (recordingId: string) => {
        const recording = recordingsRef.current.find(r => r.id === recordingId)
        if (!recording) return
        if (recording.uploadState === 'uploading') return
        if (recording.uploadState === 'uploaded') return

        updateRecording(recordingId, rec => ({ ...rec, uploadState: 'uploading', uploadError: undefined, uploadProgress: rec.uploadProgress || 0 }))

        try {
            const parts = splitBlobIntoParts(recording.blob)
            if (parts.length === 0) throw new Error('Recording is empty')

            let uploadId = recording.uploadSessionId
            let uploadedPartSet = new Set<number>()

            if (uploadId) {
                const session = await requestWithAuth<UploadSessionResponse>(`/upload/${uploadId}`)
                if (session.status === 'completed') {
                    updateRecording(recordingId, rec => ({ ...rec, uploadState: 'uploaded', uploadProgress: 100, uploadedObjectKey: session.object_key }))
                    return
                }
                if (session.status === 'failed') { uploadId = undefined }
                else { uploadedPartSet = new Set<number>(session.uploaded_parts) }
            }

            if (!uploadId) {
                const initPayload = await requestWithAuth<UploadInitResponse>('/upload/init', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filename: `${recording.name}.webm`, content_type: recording.blob.type || 'video/webm', total_parts: parts.length, total_size: recording.blob.size }),
                })
                uploadId = initPayload.upload_id
                uploadedPartSet = new Set<number>()
                updateRecording(recordingId, rec => ({ ...rec, uploadSessionId: uploadId }))
            }

            const pendingParts = parts.filter(({ partNumber }) => !uploadedPartSet.has(partNumber))
            let completedCount = uploadedPartSet.size
            const totalCount = parts.length
            updateRecording(recordingId, rec => ({ ...rec, uploadProgress: Math.floor((completedCount / totalCount) * 100) }))

            if (pendingParts.length > 0) {
                let cursor = 0
                const worker = async () => {
                    while (true) {
                        const currentIndex = cursor++
                        if (currentIndex >= pendingParts.length) return
                        const { partNumber, chunk } = pendingParts[currentIndex]
                        await uploadPartWithRetry(uploadId!, partNumber, chunk, partNumber === totalCount)
                        completedCount += 1
                        updateRecording(recordingId, rec => ({ ...rec, uploadProgress: Math.floor((completedCount / totalCount) * 100) }))
                    }
                }
                await Promise.all(Array.from({ length: Math.min(UPLOAD_CONCURRENCY, pendingParts.length) }, () => worker()))
            }

            const complete = await requestWithAuth<UploadCompleteResponse>('/upload/complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ upload_id: uploadId }),
            })
            updateRecording(recordingId, rec => ({ ...rec, uploadState: 'uploaded', uploadProgress: 100, uploadedObjectKey: complete.object_key, uploadedAssetId: complete.asset_id, uploadError: undefined }))
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Upload failed'
            updateRecording(recordingId, rec => ({ ...rec, uploadState: 'failed', uploadError: message }))
        }
    }, [requestWithAuth, splitBlobIntoParts, updateRecording, uploadPartWithRetry])

    return (
        <div className='record-workspace' style={{ display: isVisible ? undefined : 'none' }}>
            <div className="record-panel">
                {error && <div className="record-error">{error}</div>}

                <div className="record-capture-grid">
                    {/* Screen recording */}
                    <div className={`record-capture-card ${isRecordingScreen ? 'recording' : ''}`}>
                        <div className="record-capture-icon"><Monitor size={20} /></div>
                        <div className="record-capture-info">
                            <div className="record-capture-title">Screen record</div>
                            <div className="record-capture-sub">
                                {isRecordingScreen ? (
                                    <span className="record-live-badge">
                                        <span className="record-dot" />
                                        {formatDuration(screenDuration)}
                                    </span>
                                ) : 'Quay lại màn hình hoặc tab'}
                            </div>
                        </div>
                        <button type="button" className={`record-btn ${isRecordingScreen ? 'record-btn--stop' : ''}`}
                            onClick={isRecordingScreen ? stopScreenRecording : startScreenRecording}>
                            {isRecordingScreen ? <><VideoOff size={13} /> Dừng</> : <><Video size={13} /> Bắt đầu</>}
                        </button>
                    </div>

                    {/* Audio recording */}
                    <div className={`record-capture-card ${isRecordingAudio ? 'recording' : ''}`}>
                        <div className="record-capture-icon"><Mic size={20} /></div>
                        <div className="record-capture-info">
                            <div className="record-capture-title">Ghi âm</div>
                            <div className="record-capture-sub">
                                {isRecordingAudio ? (
                                    <span className="record-live-badge">
                                        <span className="record-dot" />
                                        {formatDuration(audioDuration)}
                                    </span>
                                ) : 'Ghi âm từ microphone'}
                            </div>
                        </div>
                        <button type="button" className={`record-btn ${isRecordingAudio ? 'record-btn--stop' : ''}`}
                            onClick={isRecordingAudio ? stopAudioRecording : startAudioRecording}>
                            {isRecordingAudio ? <><MicOff size={13} /> Dừng</> : <><Mic size={13} /> Bắt đầu</>}
                        </button>
                    </div>
                </div>

                {/* Video preview player */}
                <div className="record-video-container" style={{ display: hasVideos ? 'block' : 'none' }}>
                    <video ref={videoElRef} className="record-video-preview" controls style={{ width: '100%' }} />
                    {activeVideoId && (
                        <div className="record-video-label">
                            {activeVideoLabel || recordings.find(r => r.id === activeVideoId)?.name || ''}
                        </div>
                    )}
                </div>

                {/* Audio preview player */}
                <div className="record-video-container" style={{ display: hasAudioPreview ? 'block' : 'none' }}>
                    <audio ref={audioElRef} controls className="record-audio-player" />
                    {activeAudioId && (
                        <div className="record-video-label">
                            {activeAudioLabel || recordings.find(r => r.id === activeAudioId)?.name || ''}
                        </div>
                    )}
                </div>

                <RecordingsList
                    requestWithAuth={requestWithAuth}
                    recordings={recordings}
                    playingId={playingId}
                    onPlay={handlePlay}
                    onPlayServerVideo={handlePlayServerVideo}
                    onPlayServerAudio={handlePlayServerAudio}
                    onUpload={(recordingId) => void handleUpload(recordingId)}
                    onDownload={handleDownload}
                    onDelete={handleDelete}
                    activeStream={activeStream}
                    recordingType={recordingType}
                    onViewKnowledge={(assetId) => navigate(`/assets/${assetId}/knowledge`)}
                    workspaceId={workspaceId}
                    onAssetChange={onAssetChange}
                />
            </div>
        </div>
    )
}