import { useCallback, useEffect, useRef, useState } from 'react'
import {
    AlertCircle, ArrowLeft, BookOpen, Brain, Clock, FileText,
    Hash, Lightbulb, MessageSquare, Mic, Monitor,
    RefreshCw, Star, Tag, Target, TrendingUp, Zap
} from 'lucide-react'
import type { AuthRequest } from './recordingTypes'
import { ApiError } from '../services/api'

/* ─────────────────── Types ─────────────────── */

type KeyQuote = {
    quote: string
    start_sec: number
    context?: string
}

type KnowledgeTimelineEntry = {
    start_sec: number
    end_sec: number
    activity_summary: string
    event_type: string
    knowledge_value: number
    application?: string
    keywords?: string[]
    screen_content?: string
    screen_type?: string
    spoken_content?: string
    topics?: string[]
}

type WorkflowStep = {
    step: number
    description: string
    start_sec: number
    end_sec: number
}

type ProblemItem = {
    problem: string
    context?: string
    resolution?: string
    time_to_resolve_sec?: number
    start_sec?: number
    end_sec?: number
}

type SolutionItem = {
    problem: string
    solution: string
    generalizability?: number
    start_sec?: number
    end_sec?: number
}

type AssetKnowledgeSummary = {
    _id: string
    asset_id: string
    cost_usd: number
    created_at: string
    difficulty_level: string
    has_audio: boolean
    has_video: boolean
    key_quotes: KeyQuote[]
    knowledge_gained: string[]
    knowledge_timeline: KnowledgeTimelineEntry[]
    llm_model: string
    ocr_job_id: string
    overall_summary: string
    primary_technology?: string
    secondary_technologies?: string[]
    problems_encountered: ProblemItem[]
    solutions_found: SolutionItem[]
    session_title: string
    status: string
    synthesized_at: string
    tags: string[]
    tokens_used: number
    updated_at: string
    user_id: string
    workflow: WorkflowStep[]
}

type UploadAccessUrlResponse = {
    upload_id: string
    object_key: string
    url: string
    expires_in_seconds: number
}

type AssetResponse = {
    id: string
    type: string
    status: string
    title: string | null
    source_upload_id: string | null
    source_object_key: string
}

type AssetKnowledgeViewProps = {
    assetId: string
    assetTitle?: string
    requestWithAuth: AuthRequest
    onClose: () => void
}

/* ─────────────────── Helpers ─────────────────── */

function formatSeconds(sec: number): string {
    const m = Math.floor(sec / 60)
    const s = Math.floor(sec % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
}

function difficultyColor(level: string): string {
    switch (level?.toLowerCase()) {
        case 'beginner': return 'akv-badge--green'
        case 'intermediate': return 'akv-badge--yellow'
        case 'advanced': return 'akv-badge--red'
        default: return 'akv-badge--gray'
    }
}

function difficultyLabel(level: string): string {
    const map: Record<string, string> = { beginner: 'Beginner', intermediate: 'Intermediate', advanced: 'Advanced' }
    return map[level?.toLowerCase()] ?? level
}

function KnowledgeBar({ value }: { value: number }) {
    const pct = Math.round(value * 100)
    const color = value >= 0.7 ? 'var(--green)' : value >= 0.4 ? 'var(--yellow)' : 'var(--text-tertiary)'
    return (
        <div className="akv-kbar">
            <div className="akv-kbar-track">
                <div className="akv-kbar-fill" style={{ width: `${pct}%`, background: color }} />
            </div>
            <span className="akv-kbar-label" style={{ color }}>{pct}%</span>
        </div>
    )
}

/* ─────────────────── Inline Player ─────────────────── */

type InlinePlayerProps = {
    url: string
    isAudio: boolean
    onTimeUpdate: (t: number) => void
    onPlay: () => void
    onPause: () => void
    onEnded: () => void
    mediaRef: React.RefObject<HTMLVideoElement | HTMLAudioElement | null>
}

function InlinePlayer({ url, isAudio, onTimeUpdate, onPlay, onPause, onEnded, mediaRef }: InlinePlayerProps) {
    const handleTimeUpdate = (e: React.SyntheticEvent<HTMLVideoElement | HTMLAudioElement>) => {
        onTimeUpdate(e.currentTarget.currentTime)
    }

    return (
        <div className="akv-player">
            {isAudio ? (
                <audio
                    ref={mediaRef as React.RefObject<HTMLAudioElement>}
                    src={url}
                    onTimeUpdate={handleTimeUpdate}
                    onPlay={onPlay}
                    onPause={onPause}
                    onEnded={onEnded}
                    controls
                    style={{ width: '100%' }}
                />
            ) : (
                <video
                    ref={mediaRef as React.RefObject<HTMLVideoElement>}
                    src={url}
                    className="akv-player-video"
                    onTimeUpdate={handleTimeUpdate}
                    onPlay={onPlay}
                    onPause={onPause}
                    onEnded={onEnded}
                    playsInline
                    controls
                />
            )}
        </div>
    )
}

/* ─────────────────── Main component ─────────────────── */

export function AssetKnowledgeView({ assetId, requestWithAuth, onClose }: AssetKnowledgeViewProps) {
    const [data, setData] = useState<AssetKnowledgeSummary | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')
    const [summaryExists, setSummaryExists] = useState(true)
    const [isProcessing, setIsProcessing] = useState(false)
    const [activeTab, setActiveTab] = useState<'overview' | 'timeline' | 'workflow'>('overview')

    // Player state
    const [mediaUrl, setMediaUrl] = useState<string | null>(null)
    const [isAudioAsset, setIsAudioAsset] = useState(false)
    const [isPlaying, setIsPlaying] = useState(false)
    const [currentTime, setCurrentTime] = useState(0)
    const [loadingMedia, setLoadingMedia] = useState(false)
    const mediaRef = useRef<HTMLVideoElement | HTMLAudioElement | null>(null)

    // Active indices for highlighting
    const activeTimelineIdx = data?.knowledge_timeline
        ? data.knowledge_timeline.findIndex(e => currentTime >= e.start_sec && currentTime < e.end_sec)
        : -1
    const activeWorkflowIdx = data?.workflow
        ? data.workflow.findIndex(s => currentTime >= s.start_sec && currentTime < s.end_sec)
        : -1

    // Scroll active entries into view
    const timelineRefs = useRef<(HTMLDivElement | null)[]>([])
    const workflowRefs = useRef<(HTMLDivElement | null)[]>([])

    useEffect(() => {
        if (activeTimelineIdx >= 0 && activeTab === 'timeline') {
            timelineRefs.current[activeTimelineIdx]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        }
    }, [activeTimelineIdx, activeTab])

    useEffect(() => {
        if (activeWorkflowIdx >= 0 && activeTab === 'workflow') {
            workflowRefs.current[activeWorkflowIdx]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        }
    }, [activeWorkflowIdx, activeTab])

    const load = useCallback(async () => {
        setLoading(true)
        setError('')
        try {
            const result = await requestWithAuth<AssetKnowledgeSummary>(`/knowledge/assets/${assetId}/summary`)
            setData(result)
            setSummaryExists(true)
        } catch (err) {
            // Check if it's a 404 (summary not found)
            if (err instanceof ApiError && err.status === 404) {
                setSummaryExists(false)
                setData(null)
            } else {
                setError(err instanceof Error ? err.message : 'Cannot load knowledge summary')
                setSummaryExists(true)
            }
        } finally {
            setLoading(false)
        }
    }, [assetId, requestWithAuth])

    useEffect(() => { void load() }, [load])

    // Load media URL from asset
    useEffect(() => {
        let cancelled = false
        const fetchMedia = async () => {
            setLoadingMedia(true)
            try {
                const asset = await requestWithAuth<AssetResponse>(`/assets/${assetId}`)
                if (!asset.source_upload_id) return
                const resp = await requestWithAuth<UploadAccessUrlResponse>(
                    `/upload/access?upload_id=${asset.source_upload_id}&disposition=inline`
                )
                if (!cancelled) {
                    setMediaUrl(resp.url)
                    setIsAudioAsset(asset.type?.toLowerCase().includes('audio') ?? false)
                }
            } catch {
                // Media is optional — don't block UI
            } finally {
                if (!cancelled) setLoadingMedia(false)
            }
        }
        void fetchMedia()
        return () => { cancelled = true }
    }, [assetId, requestWithAuth])

    const handlePlay = useCallback(() => setIsPlaying(true), [])
    const handlePause = useCallback(() => setIsPlaying(false), [])
    const handleEnded = useCallback(() => setIsPlaying(false), [])

    const seekTo = useCallback((seconds: number) => {
        const el = mediaRef.current
        if (el) {
            el.currentTime = seconds
            setCurrentTime(seconds)
            if (!isPlaying) {
                void el.play()
                setIsPlaying(true)
            }
        }
    }, [isPlaying])

    const triggerProcess = useCallback(async () => {
        setIsProcessing(true)
        setError('')
        try {
            await requestWithAuth(`/assets/${assetId}/process`, {
                method: 'POST'
            })
            // // Poll for summary every 3 seconds
            // const pollInterval = setInterval(async () => {
            //     try {
            //         const result = await requestWithAuth<AssetKnowledgeSummary>(`/knowledge/assets/${assetId}/summary`)
            //         setData(result)
            //         setSummaryExists(true)
            //         setIsProcessing(false)
            //         clearInterval(pollInterval)
            //     } catch {
            //         // Still processing, continue polling
            //     }
            // }, 3000)
            
            // // Stop polling after 5 minutes
            // setTimeout(() => {
            //     clearInterval(pollInterval)
            //     setIsProcessing(false)
            // }, 300000)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to start processing')
            setIsProcessing(false)
        }
    }, [assetId, requestWithAuth])

    /* ── Loading / Error ── */
    if (loading) return (
        <div className="akv-root">
            <div className="akv-topbar">
                <button type="button" className="akv-back-btn" onClick={onClose}><ArrowLeft size={14} /><span>Back</span></button>
            </div>
            <div className="akv-loading"><RefreshCw size={20} className="akv-spin" /><span>Loading knowledge summary…</span></div>
        </div>
    )

    if (error) return (
        <div className="akv-root">
            <div className="akv-topbar">
                <button type="button" className="akv-back-btn" onClick={onClose}><ArrowLeft size={14} /><span>Back</span></button>
            </div>
            <div className="akv-error"><AlertCircle size={16} /><span>{error}</span>
                <button type="button" className="akv-retry-btn" onClick={load}>Retry</button>
            </div>
        </div>
    )

    // Show trigger button when summary doesn't exist yet
    if (!summaryExists && !loading) {
        return (
            <div className="akv-root">
                <div className="akv-topbar">
                    <button type="button" className="akv-back-btn" onClick={onClose}><ArrowLeft size={14} /><span>Back</span></button>
                </div>
                <div className="akv-body">
                    {/* Keep media player visible */}
                    {mediaUrl && (
                        <InlinePlayer
                            url={mediaUrl}
                            isAudio={isAudioAsset}
                            onTimeUpdate={setCurrentTime}
                            onPlay={handlePlay}
                            onPause={handlePause}
                            onEnded={handleEnded}
                            mediaRef={mediaRef}
                        />
                    )}
                    
                    <div className="akv-no-summary">
                        <Brain size={48} style={{ marginBottom: 16, opacity: 0.3 }} />
                        <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>
                            Knowledge Summary Not Generated
                        </h2>
                        <p style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 24, maxWidth: 400, textAlign: 'center' }}>
                            This asset hasn't been processed for knowledge extraction yet. 
                            Click the button below to start the analysis.
                        </p>
                        <button 
                            type="button" 
                            className="btn btn-primary" 
                            onClick={triggerProcess}
                            disabled={isProcessing}
                        >
                            {isProcessing ? (
                                <>
                                    <RefreshCw size={16} className="akv-spin" />
                                    Processing...
                                </>
                            ) : (
                                <>
                                    <Zap size={16} />
                                    Generate Knowledge Summary
                                </>
                            )}
                        </button>
                    </div>
                </div>
            </div>
        )
    }

    if (!data) return null

    const problems: ProblemItem[] = (data.problems_encountered ?? []).map(p =>
        typeof p === 'string' ? { problem: p } : p
    )
    const solutions: SolutionItem[] = (data.solutions_found ?? []).map(s =>
        typeof s === 'string' ? { problem: '', solution: s } : s
    )

    return (
        <div className="akv-root">
            {/* ── Top bar ── */}
            <div className="akv-topbar">
                <button type="button" className="akv-back-btn" onClick={onClose}><ArrowLeft size={14} /><span>Back</span></button>
                <div className="akv-topbar-meta">
                    <span className="akv-topbar-status">
                        <span className={`akv-status-dot ${data.status === 'completed' ? 'akv-status-dot--ok' : ''}`} />
                        {data.status}
                    </span>
                </div>
            </div>

            <div className="akv-body">
                {/* ── Hero ── */}
                <div className="akv-hero">
                    <div className="akv-hero-icon"><Brain size={22} /></div>
                    <div className="akv-hero-text">
                        <h1 className="akv-title">{data.session_title}</h1>
                        <div className="akv-hero-badges">
                            <span className={`akv-badge ${difficultyColor(data.difficulty_level)}`}>
                                {difficultyLabel(data.difficulty_level)}
                            </span>
                            {data.has_video && <span className="akv-badge akv-badge--gray"><Monitor size={10} />Video</span>}
                            {data.has_audio && <span className="akv-badge akv-badge--gray"><Mic size={10} />Audio</span>}
                            {data.primary_technology && <span className="akv-badge akv-badge--gray"><Zap size={10} />{data.primary_technology}</span>}
                        </div>
                    </div>
                </div>

                {/* ── Media Player ── */}
                {mediaUrl ? (
                    <InlinePlayer
                        url={mediaUrl}
                        isAudio={isAudioAsset}
                        onTimeUpdate={setCurrentTime}
                        onPlay={handlePlay}
                        onPause={handlePause}
                        onEnded={handleEnded}
                        mediaRef={mediaRef}
                    />
                ) : loadingMedia ? (
                    <div className="akv-media-loading">
                        <RefreshCw size={12} className="akv-spin" />
                        <span>Loading media…</span>
                    </div>
                ) : null}

                {/* ── Tabs ── */}
                <div className="akv-tabs">
                    <button type="button" className={`akv-tab ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>
                        <BookOpen size={13} />Overview
                    </button>
                    <button type="button" className={`akv-tab ${activeTab === 'timeline' ? 'active' : ''}`} onClick={() => setActiveTab('timeline')}>
                        <Clock size={13} />Timeline
                        {activeTimelineIdx >= 0 && isPlaying && <span className="akv-tab-live-dot" />}
                    </button>
                    <button type="button" className={`akv-tab ${activeTab === 'workflow' ? 'active' : ''}`} onClick={() => setActiveTab('workflow')}>
                        <Target size={13} />Workflow
                        {activeWorkflowIdx >= 0 && isPlaying && <span className="akv-tab-live-dot" />}
                    </button>
                </div>

                {/* ── Overview Tab ── */}
                {activeTab === 'overview' && (
                    <div className="akv-tab-content">
                        <div className="akv-card">
                            <div className="akv-card-header"><FileText size={14} /><span>Session Summary</span></div>
                            <p className="akv-summary-text">{data.overall_summary}</p>
                        </div>

                        {(data.knowledge_gained?.length ?? 0) > 0 && (
                            <div className="akv-card">
                                <div className="akv-card-header">
                                    <Lightbulb size={14} /><span>Knowledge Gained</span>
                                    <span className="akv-card-count">{data.knowledge_gained.length}</span>
                                </div>
                                <ul className="akv-insight-list">
                                    {data.knowledge_gained.map((item, i) => (
                                        <li key={i} className="akv-insight-item">
                                            <span className="akv-insight-dot" />
                                            <span>{typeof item === 'string' ? item : JSON.stringify(item)}</span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )}

                        {(data.key_quotes?.length ?? 0) > 0 && (
                            <div className="akv-card">
                                <div className="akv-card-header"><MessageSquare size={14} /><span>Key Quotes</span></div>
                                <div className="akv-quotes">
                                    {data.key_quotes.map((q, i) => (
                                        <div key={i} className="akv-quote">
                                            <div className="akv-quote-text">"{q.quote}"</div>
                                            <div className="akv-quote-meta">
                                                {q.context && <span className="akv-quote-context">{q.context}</span>}
                                                <button type="button" className="akv-time-chip" onClick={() => seekTo(q.start_sec)}>
                                                    <Clock size={9} />{formatSeconds(q.start_sec)}
                                                </button>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        <div className="akv-two-col">
                            <div className="akv-card">
                                <div className="akv-card-header">
                                    <AlertCircle size={14} /><span>Problems</span>
                                    <span className="akv-card-count">{problems.length}</span>
                                </div>
                                {problems.length === 0
                                    ? <div className="akv-empty-mini">None encountered</div>
                                    : <ul className="akv-insight-list">
                                        {problems.map((p, i) => (
                                            <li key={i} className="akv-insight-item akv-insight-item--red">
                                                <span className="akv-insight-dot" />
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1 }}>
                                                    <span>{p.problem}</span>
                                                    {p.resolution && <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>→ {p.resolution}</span>}
                                                    {p.start_sec !== undefined && (
                                                        <button type="button" className="akv-time-chip" style={{ alignSelf: 'flex-start', marginTop: 2 }} onClick={() => seekTo(p.start_sec!)}>
                                                            <Clock size={9} />{formatSeconds(p.start_sec)}
                                                        </button>
                                                    )}
                                                </div>
                                            </li>
                                        ))}
                                    </ul>
                                }
                            </div>
                            <div className="akv-card">
                                <div className="akv-card-header">
                                    <Star size={14} /><span>Solutions</span>
                                    <span className="akv-card-count">{solutions.length}</span>
                                </div>
                                {solutions.length === 0
                                    ? <div className="akv-empty-mini">None recorded</div>
                                    : <ul className="akv-insight-list">
                                        {solutions.map((s, i) => (
                                            <li key={i} className="akv-insight-item akv-insight-item--green">
                                                <span className="akv-insight-dot" />
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1 }}>
                                                    <span>{s.solution}</span>
                                                    {s.problem && <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>For: {s.problem}</span>}
                                                    {s.start_sec !== undefined && (
                                                        <button type="button" className="akv-time-chip" style={{ alignSelf: 'flex-start', marginTop: 2 }} onClick={() => seekTo(s.start_sec!)}>
                                                            <Clock size={9} />{formatSeconds(s.start_sec)}
                                                        </button>
                                                    )}
                                                </div>
                                            </li>
                                        ))}
                                    </ul>
                                }
                            </div>
                        </div>

                        <div className="akv-two-col">
                            {(data.primary_technology || (data.secondary_technologies?.length ?? 0) > 0) && (
                                <div className="akv-card">
                                    <div className="akv-card-header"><Hash size={14} /><span>Technologies</span></div>
                                    <div className="akv-tag-cloud">
                                        {data.primary_technology && <span className="akv-tech-chip akv-tech-chip--primary">{data.primary_technology}</span>}
                                        {(data.secondary_technologies ?? []).map((t, i) => <span key={i} className="akv-tech-chip">{t}</span>)}
                                    </div>
                                </div>
                            )}
                            {(data.tags?.length ?? 0) > 0 && (
                                <div className="akv-card">
                                    <div className="akv-card-header"><Tag size={14} /><span>Tags</span></div>
                                    <div className="akv-tag-cloud">
                                        {data.tags.map((tag, i) => <span key={i} className="akv-tag-chip">{tag}</span>)}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* ── Timeline Tab ── */}
                {activeTab === 'timeline' && (
                    <div className="akv-tab-content">
                        {(data.knowledge_timeline?.length ?? 0) === 0
                            ? <div className="akv-empty-state">No timeline data available.</div>
                            : (
                                <div className="akv-timeline">
                                    {data.knowledge_timeline.map((entry, i) => {
                                        const isActive = i === activeTimelineIdx
                                        return (
                                            <div
                                                key={i}
                                                ref={el => { timelineRefs.current[i] = el }}
                                                className={`akv-tl-entry ${isActive ? 'akv-tl-entry--active' : ''}`}
                                            >
                                                <div className="akv-tl-time">
                                                    <button
                                                        type="button"
                                                        className={`akv-time-chip akv-time-chip--lg ${isActive ? 'akv-time-chip--active' : ''}`}
                                                        onClick={() => seekTo(entry.start_sec)}
                                                    >
                                                        {isActive && <span className="akv-time-chip-live" />}
                                                        {formatSeconds(entry.start_sec)}
                                                    </button>
                                                    <div className="akv-tl-duration">{formatSeconds(entry.end_sec - entry.start_sec)}</div>
                                                </div>

                                                <div className="akv-tl-connector">
                                                    <div className={`akv-tl-dot ${isActive ? 'akv-tl-dot--active' : ''}`} />
                                                    {i < data.knowledge_timeline.length - 1 && (
                                                        <div className={`akv-tl-line ${isActive ? 'akv-tl-line--active' : ''}`} />
                                                    )}
                                                </div>

                                                <div className="akv-tl-content">
                                                    <div className="akv-tl-header">
                                                        <div className="akv-tl-badges">
                                                            {entry.screen_type && <span className="akv-badge akv-badge--gray">{entry.screen_type}</span>}
                                                            <span className="akv-badge akv-badge--gray">{entry.event_type}</span>
                                                            {isActive && (
                                                                <span className="akv-badge akv-badge--playing">
                                                                    <span className="akv-badge-pulse" />Playing
                                                                </span>
                                                            )}
                                                        </div>
                                                        <KnowledgeBar value={entry.knowledge_value} />
                                                    </div>

                                                    <p className="akv-tl-summary">{entry.activity_summary}</p>

                                                    {entry.screen_content && (
                                                        <div className="akv-tl-screen"><Monitor size={10} /><span>{entry.screen_content}</span></div>
                                                    )}
                                                    {entry.spoken_content && (
                                                        <div className="akv-tl-spoken"><Mic size={10} /><span>{entry.spoken_content}</span></div>
                                                    )}
                                                    {entry.application && (
                                                        <div className="akv-tl-application"><TrendingUp size={10} /><span>{entry.application}</span></div>
                                                    )}

                                                    {((entry.topics?.length ?? 0) > 0 || (entry.keywords?.length ?? 0) > 0) && (
                                                        <div className="akv-tl-tags">
                                                            {(entry.topics ?? []).map((t, j) => <span key={j} className="akv-tag-chip akv-tag-chip--sm">{t}</span>)}
                                                            {(entry.keywords ?? []).map((k, j) => <span key={j} className="akv-kw-chip">{k}</span>)}
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        )
                                    })}
                                </div>
                            )
                        }
                    </div>
                )}

                {/* ── Workflow Tab ── */}
                {activeTab === 'workflow' && (
                    <div className="akv-tab-content">
                        {(data.workflow?.length ?? 0) === 0
                            ? <div className="akv-empty-state">No workflow steps recorded.</div>
                            : (
                                <div className="akv-workflow">
                                    {data.workflow.map((step, i) => {
                                        const isActive = i === activeWorkflowIdx
                                        return (
                                            <div
                                                key={step.step}
                                                ref={el => { workflowRefs.current[i] = el }}
                                                className={`akv-wf-step ${isActive ? 'akv-wf-step--active' : ''}`}
                                            >
                                                <div className={`akv-wf-number ${isActive ? 'akv-wf-number--active' : ''}`}>
                                                    {isActive
                                                        ? <span className="akv-wf-playing-dot" />
                                                        : step.step
                                                    }
                                                </div>
                                                <div className="akv-wf-body">
                                                    <div className="akv-wf-title-row">
                                                        <p className="akv-wf-desc">{step.description}</p>
                                                        {isActive && (
                                                            <span className="akv-wf-now-badge">
                                                                <span className="akv-wf-now-dot" />Now
                                                            </span>
                                                        )}
                                                    </div>
                                                    <div className="akv-wf-time">
                                                        <button
                                                            type="button"
                                                            className={`akv-time-chip ${isActive ? 'akv-time-chip--active' : ''}`}
                                                            onClick={() => seekTo(step.start_sec)}
                                                        >
                                                            <Clock size={9} />{formatSeconds(step.start_sec)}
                                                        </button>
                                                        <span className="akv-wf-arrow">→</span>
                                                        <button type="button" className="akv-time-chip" onClick={() => seekTo(step.end_sec)}>
                                                            <Clock size={9} />{formatSeconds(step.end_sec)}
                                                        </button>
                                                        <span className="akv-wf-dur">({formatSeconds(step.end_sec - step.start_sec)})</span>
                                                    </div>
                                                </div>
                                            </div>
                                        )
                                    })}
                                </div>
                            )
                        }
                    </div>
                )}
            </div>
        </div>
    )
}