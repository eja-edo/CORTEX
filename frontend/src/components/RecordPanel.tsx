import { useCallback, useEffect, useRef, useState } from 'react'
import { Download, Mic, MicOff, Monitor, Play, Square, Trash2, Video, VideoOff } from 'lucide-react'

type RecordingType = 'audio' | 'video'

type Recording = {
    id: string
    type: RecordingType
    name: string
    blob: Blob
    url: string
    duration: number
    createdAt: Date
}

function formatDuration(seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${s.toString().padStart(2, '0')}`
}

function formatDate(date: Date): string {
    return date.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' }) +
        ' ' + date.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
}

export function RecordPanel() {
    const [recordings, setRecordings] = useState<Recording[]>([])
    const [isRecordingAudio, setIsRecordingAudio] = useState(false)
    const [isRecordingScreen, setIsRecordingScreen] = useState(false)
    const [audioDuration, setAudioDuration] = useState(0)
    const [screenDuration, setScreenDuration] = useState(0)
    const [playingId, setPlayingId] = useState<string | null>(null)
    const [error, setError] = useState<string>('')

    const audioRecorderRef = useRef<MediaRecorder | null>(null)
    const screenRecorderRef = useRef<MediaRecorder | null>(null)
    const audioChunksRef = useRef<Blob[]>([])
    const screenChunksRef = useRef<Blob[]>([])
    const audioTimerRef = useRef<number | null>(null)
    const screenTimerRef = useRef<number | null>(null)
    const audioElRef = useRef<HTMLAudioElement | null>(null)
    const videoElRef = useRef<HTMLVideoElement | null>(null)
    const audioStreamRef = useRef<MediaStream | null>(null)
    const screenStreamRef = useRef<MediaStream | null>(null)

    useEffect(() => {
        return () => {
            if (audioTimerRef.current) clearInterval(audioTimerRef.current)
            if (screenTimerRef.current) clearInterval(screenTimerRef.current)
            audioStreamRef.current?.getTracks().forEach(t => t.stop())
            screenStreamRef.current?.getTracks().forEach(t => t.stop())
            recordings.forEach(r => URL.revokeObjectURL(r.url))
        }
    }, [])

    const startAudioRecording = useCallback(async () => {
        setError('')
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
            audioStreamRef.current = stream
            const recorder = new MediaRecorder(stream)
            audioRecorderRef.current = recorder
            audioChunksRef.current = []
            recorder.ondataavailable = e => { if (e.data.size > 0) audioChunksRef.current.push(e.data) }
            recorder.onstop = () => {
                const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
                const url = URL.createObjectURL(blob)
                const dur = audioDuration
                setRecordings(prev => [{
                    id: Date.now().toString(),
                    type: 'audio',
                    name: `Ghi âm ${formatDate(new Date())}`,
                    blob, url,
                    duration: dur,
                    createdAt: new Date(),
                }, ...prev])
                setAudioDuration(0)
                stream.getTracks().forEach(t => t.stop())
                audioStreamRef.current = null
            }
            recorder.start(200)
            setIsRecordingAudio(true)
            audioTimerRef.current = window.setInterval(() => setAudioDuration(d => d + 1), 1000)
        } catch {
            setError('Không thể truy cập microphone. Hãy cho phép quyền truy cập.')
        }
    }, [audioDuration])

    const stopAudioRecording = useCallback(() => {
        if (audioTimerRef.current) { clearInterval(audioTimerRef.current); audioTimerRef.current = null }
        audioRecorderRef.current?.stop()
        setIsRecordingAudio(false)
    }, [])

    const startScreenRecording = useCallback(async () => {
        setError('')
        try {
            const stream = await navigator.mediaDevices.getDisplayMedia({
                video: true,
                audio: true,
            })
            screenStreamRef.current = stream
            const recorder = new MediaRecorder(stream)
            screenRecorderRef.current = recorder
            screenChunksRef.current = []
            recorder.ondataavailable = e => { if (e.data.size > 0) screenChunksRef.current.push(e.data) }
            recorder.onstop = () => {
                const blob = new Blob(screenChunksRef.current, { type: 'video/webm' })
                const url = URL.createObjectURL(blob)
                const dur = screenDuration
                setRecordings(prev => [{
                    id: Date.now().toString(),
                    type: 'video',
                    name: `Màn hình ${formatDate(new Date())}`,
                    blob, url,
                    duration: dur,
                    createdAt: new Date(),
                }, ...prev])
                setScreenDuration(0)
                stream.getTracks().forEach(t => t.stop())
                screenStreamRef.current = null
            }
            stream.getVideoTracks()[0].onended = () => {
                stopScreenRecording()
            }
            recorder.start(200)
            setIsRecordingScreen(true)
            screenTimerRef.current = window.setInterval(() => setScreenDuration(d => d + 1), 1000)
        } catch {
            setError('Không thể bắt đầu quay màn hình.')
        }
    }, [screenDuration])

    const stopScreenRecording = useCallback(() => {
        if (screenTimerRef.current) { clearInterval(screenTimerRef.current); screenTimerRef.current = null }
        screenRecorderRef.current?.stop()
        setIsRecordingScreen(false)
    }, [])

    const handlePlay = useCallback((rec: Recording) => {
        if (playingId === rec.id) {
            audioElRef.current?.pause()
            videoElRef.current?.pause()
            setPlayingId(null)
            return
        }
        setPlayingId(rec.id)
        if (rec.type === 'audio') {
            if (!audioElRef.current) audioElRef.current = new Audio()
            const el = audioElRef.current
            el.src = rec.url
            el.onended = () => setPlayingId(null)
            el.play()
        } else {
            if (videoElRef.current) {
                videoElRef.current.src = rec.url
                videoElRef.current.play()
                videoElRef.current.onended = () => setPlayingId(null)
            }
        }
    }, [playingId])

    const handleDownload = useCallback((rec: Recording) => {
        const a = document.createElement('a')
        a.href = rec.url
        a.download = rec.name + (rec.type === 'audio' ? '.webm' : '.webm')
        a.click()
    }, [])

    const handleDelete = useCallback((id: string) => {
        setRecordings(prev => {
            const rec = prev.find(r => r.id === id)
            if (rec) URL.revokeObjectURL(rec.url)
            return prev.filter(r => r.id !== id)
        })
        if (playingId === id) {
            audioElRef.current?.pause()
            videoElRef.current?.pause()
            setPlayingId(null)
        }
    }, [playingId])

    return (
        <div className="record-panel">
            {error && (
                <div className="record-error">{error}</div>
            )}

            {/* Capture cards */}
            <div className="record-capture-grid">
                {/* Screen recording */}
                <div className={`record-capture-card ${isRecordingScreen ? 'recording' : ''}`}>
                    <div className="record-capture-icon">
                        <Monitor size={20} />
                    </div>
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
                    <button
                        type="button"
                        className={`record-btn ${isRecordingScreen ? 'record-btn--stop' : ''}`}
                        onClick={isRecordingScreen ? stopScreenRecording : startScreenRecording}
                        aria-label={isRecordingScreen ? 'Dừng quay màn hình' : 'Bắt đầu quay màn hình'}
                    >
                        {isRecordingScreen ? <><VideoOff size={13} /> Dừng</> : <><Video size={13} /> Bắt đầu</>}
                    </button>
                </div>

                {/* Audio recording */}
                <div className={`record-capture-card ${isRecordingAudio ? 'recording' : ''}`}>
                    <div className="record-capture-icon">
                        <Mic size={20} />
                    </div>
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
                    <button
                        type="button"
                        className={`record-btn ${isRecordingAudio ? 'record-btn--stop' : ''}`}
                        onClick={isRecordingAudio ? stopAudioRecording : startAudioRecording}
                        aria-label={isRecordingAudio ? 'Dừng ghi âm' : 'Bắt đầu ghi âm'}
                    >
                        {isRecordingAudio ? <><MicOff size={13} /> Dừng</> : <><Mic size={13} /> Bắt đầu</>}
                    </button>
                </div>
            </div>

            {/* Video preview for screen recordings */}
            <video
                ref={videoElRef}
                className="record-video-preview"
                controls
                style={{ display: recordings.some(r => r.type === 'video') ? 'block' : 'none' }}
            />

            {/* Recordings list */}
            {recordings.length > 0 && (
                <div className="record-list-section">
                    <div className="record-list-header">Recordings ({recordings.length})</div>
                    <div className="record-list">
                        {recordings.map(rec => (
                            <div key={rec.id} className="record-list-item">
                                <div className="record-list-icon">
                                    {rec.type === 'audio' ? <Mic size={13} /> : <Monitor size={13} />}
                                </div>
                                <div className="record-list-info">
                                    <div className="record-list-name">{rec.name}</div>
                                    <div className="record-list-meta">{formatDuration(rec.duration)} · {rec.type === 'audio' ? 'audio' : 'video'}</div>
                                </div>
                                <div className="record-list-actions">
                                    <button
                                        type="button"
                                        className={`record-action-btn ${playingId === rec.id ? 'active' : ''}`}
                                        onClick={() => handlePlay(rec)}
                                        aria-label={playingId === rec.id ? 'Dừng' : 'Phát'}
                                    >
                                        {playingId === rec.id ? <Square size={12} /> : <Play size={12} />}
                                    </button>
                                    <button
                                        type="button"
                                        className="record-action-btn"
                                        onClick={() => handleDownload(rec)}
                                        aria-label="Tải xuống"
                                    >
                                        <Download size={12} />
                                    </button>
                                    <button
                                        type="button"
                                        className="record-action-btn record-action-btn--danger"
                                        onClick={() => handleDelete(rec.id)}
                                        aria-label="Xoá"
                                    >
                                        <Trash2 size={12} />
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {recordings.length === 0 && (
                <div className="record-empty">
                    <p>Chưa có recording nào. Bắt đầu quay màn hình hoặc ghi âm.</p>
                </div>
            )}
        </div>
    )
}