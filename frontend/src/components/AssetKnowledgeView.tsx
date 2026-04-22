import { useCallback, useEffect, useState } from 'react'
import {
    AlertCircle, ArrowLeft, BookOpen, Brain, Clock, FileText,
    Hash, Lightbulb, MessageSquare, Mic, Monitor, RefreshCw,
    Star, Tag, Target, TrendingUp, Zap
} from 'lucide-react'
import type { AuthRequest } from './recordingTypes'

/* ─────────────────── Types ─────────────────── */

type KeyQuote = {
    quote: string
    start_sec: number
    context: string
}

type KnowledgeTimelineEntry = {
    start_sec: number
    end_sec: number
    activity_summary: string
    event_type: string
    knowledge_value: number
    application: string
    keywords: string[]
    screen_content: string
    screen_type: string
    spoken_content: string
    topics: string[]
}

type WorkflowStep = {
    step: number
    description: string
    start_sec: number
    end_sec: number
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
    primary_technology: string
    problems_encountered: string[]
    secondary_technologies: string[]
    session_title: string
    solutions_found: string[]
    status: string
    synthesized_at: string
    tags: string[]
    tokens_used: number
    updated_at: string
    user_id: string
    workflow: WorkflowStep[]
}

type AssetKnowledgeViewProps = {
    assetId: string
    assetTitle?: string
    requestWithAuth: AuthRequest
    onClose: () => void
    onSeek?: (seconds: number) => void
}

/* ─────────────────── Helpers ─────────────────── */

function formatSeconds(sec: number): string {
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return `${m}:${s.toString().padStart(2, '0')}`
}

function formatDate(iso: string): string {
    return new Date(iso).toLocaleString('vi-VN', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
    })
}

function difficultyColor(level: string): string {
    switch (level.toLowerCase()) {
        case 'beginner': return 'akv-badge--green'
        case 'intermediate': return 'akv-badge--yellow'
        case 'advanced': return 'akv-badge--red'
        default: return 'akv-badge--gray'
    }
}

function difficultyLabel(level: string): string {
    const map: Record<string, string> = {
        beginner: 'Beginner',
        intermediate: 'Intermediate',
        advanced: 'Advanced',
    }
    return map[level.toLowerCase()] ?? level
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

/* ─────────────────── Main component ─────────────────── */

export function AssetKnowledgeView({ assetId, assetTitle, requestWithAuth, onClose, onSeek }: AssetKnowledgeViewProps) {
    const [data, setData] = useState<AssetKnowledgeSummary | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')
    const [activeTab, setActiveTab] = useState<'overview' | 'timeline' | 'workflow'>('overview')

    const load = useCallback(async () => {
        setLoading(true)
        setError('')
        try {
            const result = await requestWithAuth<AssetKnowledgeSummary>(`/knowledge/assets/${assetId}/summary`)
            setData(result)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Cannot load knowledge summary')
        } finally {
            setLoading(false)
        }
    }, [assetId, requestWithAuth])

    useEffect(() => { void load() }, [load])

    /* ── Loading ── */
    if (loading) return (
        <div className="akv-root">
            <div className="akv-topbar">
                <button type="button" className="akv-back-btn" onClick={onClose}>
                    <ArrowLeft size={14} />
                    <span>Back</span>
                </button>
            </div>
            <div className="akv-loading">
                <RefreshCw size={20} className="akv-spin" />
                <span>Loading knowledge summary…</span>
            </div>
        </div>
    )

    /* ── Error ── */
    if (error) return (
        <div className="akv-root">
            <div className="akv-topbar">
                <button type="button" className="akv-back-btn" onClick={onClose}>
                    <ArrowLeft size={14} />
                    <span>Back</span>
                </button>
            </div>
            <div className="akv-error">
                <AlertCircle size={16} />
                <span>{error}</span>
                <button type="button" className="akv-retry-btn" onClick={load}>Retry</button>
            </div>
        </div>
    )

    if (!data) return null

    return (
        <div className="akv-root">
            {/* ── Top bar ── */}
            <div className="akv-topbar">
                <button type="button" className="akv-back-btn" onClick={onClose}>
                    <ArrowLeft size={14} />
                    <span>Back</span>
                </button>
                <div className="akv-topbar-meta">
                    <span className="akv-topbar-status">
                        <span className={`akv-status-dot ${data.status === 'completed' ? 'akv-status-dot--ok' : ''}`} />
                        {data.status}
                    </span>
                </div>
            </div>

            <div className="akv-body">
                {/* ── Hero header ── */}
                <div className="akv-hero">
                    <div className="akv-hero-icon">
                        <Brain size={22} />
                    </div>
                    <div className="akv-hero-text">
                        <h1 className="akv-title">{data.session_title}</h1>
                        <div className="akv-hero-badges">
                            <span className={`akv-badge ${difficultyColor(data.difficulty_level)}`}>
                                {difficultyLabel(data.difficulty_level)}
                            </span>
                            {data.has_video && (
                                <span className="akv-badge akv-badge--gray"><Monitor size={10} />Video</span>
                            )}
                            {data.has_audio && (
                                <span className="akv-badge akv-badge--gray"><Mic size={10} />Audio</span>
                            )}
                            <span className="akv-badge akv-badge--gray">
                                <Zap size={10} />{data.primary_technology}
                            </span>
                        </div>
                    </div>
                    <div className="akv-hero-stats">
                        <div className="akv-stat">
                            <span className="akv-stat-val">{data.knowledge_gained.length}</span>
                            <span className="akv-stat-label">Insights</span>
                        </div>
                        <div className="akv-stat">
                            <span className="akv-stat-val">{data.knowledge_timeline.length}</span>
                            <span className="akv-stat-label">Segments</span>
                        </div>
                        <div className="akv-stat">
                            <span className="akv-stat-val">{data.tokens_used.toLocaleString()}</span>
                            <span className="akv-stat-label">Tokens</span>
                        </div>
                    </div>
                </div>

                {/* ── Tabs ── */}
                <div className="akv-tabs">
                    <button type="button" className={`akv-tab ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>
                        <BookOpen size={13} />Overview
                    </button>
                    <button type="button" className={`akv-tab ${activeTab === 'timeline' ? 'active' : ''}`} onClick={() => setActiveTab('timeline')}>
                        <Clock size={13} />Timeline
                    </button>
                    <button type="button" className={`akv-tab ${activeTab === 'workflow' ? 'active' : ''}`} onClick={() => setActiveTab('workflow')}>
                        <Target size={13} />Workflow
                    </button>
                </div>

                {/* ── Overview tab ── */}
                {activeTab === 'overview' && (
                    <div className="akv-tab-content">
                        {/* Summary */}
                        <div className="akv-card">
                            <div className="akv-card-header">
                                <FileText size={14} />
                                <span>Session Summary</span>
                            </div>
                            <p className="akv-summary-text">{data.overall_summary}</p>
                        </div>

                        {/* Knowledge gained */}
                        {data.knowledge_gained.length > 0 && (
                            <div className="akv-card">
                                <div className="akv-card-header">
                                    <Lightbulb size={14} />
                                    <span>Knowledge Gained</span>
                                    <span className="akv-card-count">{data.knowledge_gained.length}</span>
                                </div>
                                <ul className="akv-insight-list">
                                    {data.knowledge_gained.map((item, i) => (
                                        <li key={i} className="akv-insight-item">
                                            <span className="akv-insight-dot" />
                                            <span>{item}</span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )}

                        {/* Key quotes */}
                        {data.key_quotes.length > 0 && (
                            <div className="akv-card">
                                <div className="akv-card-header">
                                    <MessageSquare size={14} />
                                    <span>Key Quotes</span>
                                </div>
                                <div className="akv-quotes">
                                    {data.key_quotes.map((q, i) => (
                                        <div key={i} className="akv-quote">
                                            <div className="akv-quote-text">"{q.quote}"</div>
                                            <div className="akv-quote-meta">
                                                <span className="akv-quote-context">{q.context}</span>
                                                <button
                                                    type="button"
                                                    className="akv-time-chip"
                                                    onClick={() => onSeek?.(q.start_sec)}
                                                    title="Jump to this moment"
                                                >
                                                    <Clock size={9} />{formatSeconds(q.start_sec)}
                                                </button>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Two-col: problems & solutions */}
                        <div className="akv-two-col">
                            <div className="akv-card">
                                <div className="akv-card-header">
                                    <AlertCircle size={14} />
                                    <span>Problems</span>
                                    <span className="akv-card-count">{data.problems_encountered.length}</span>
                                </div>
                                {data.problems_encountered.length === 0
                                    ? <div className="akv-empty-mini">None encountered</div>
                                    : <ul className="akv-insight-list">
                                        {data.problems_encountered.map((p, i) => (
                                            <li key={i} className="akv-insight-item akv-insight-item--red">
                                                <span className="akv-insight-dot" />
                                                <span>{p}</span>
                                            </li>
                                        ))}
                                    </ul>
                                }
                            </div>
                            <div className="akv-card">
                                <div className="akv-card-header">
                                    <Star size={14} />
                                    <span>Solutions</span>
                                    <span className="akv-card-count">{data.solutions_found.length}</span>
                                </div>
                                {data.solutions_found.length === 0
                                    ? <div className="akv-empty-mini">None recorded</div>
                                    : <ul className="akv-insight-list">
                                        {data.solutions_found.map((s, i) => (
                                            <li key={i} className="akv-insight-item akv-insight-item--green">
                                                <span className="akv-insight-dot" />
                                                <span>{s}</span>
                                            </li>
                                        ))}
                                    </ul>
                                }
                            </div>
                        </div>

                        {/* Tags & technologies */}
                        <div className="akv-two-col">
                            <div className="akv-card">
                                <div className="akv-card-header">
                                    <Hash size={14} />
                                    <span>Technologies</span>
                                </div>
                                <div className="akv-tag-cloud">
                                    <span className="akv-tech-chip akv-tech-chip--primary">{data.primary_technology}</span>
                                    {data.secondary_technologies.map((t, i) => (
                                        <span key={i} className="akv-tech-chip">{t}</span>
                                    ))}
                                </div>
                            </div>
                            <div className="akv-card">
                                <div className="akv-card-header">
                                    <Tag size={14} />
                                    <span>Tags</span>
                                </div>
                                <div className="akv-tag-cloud">
                                    {data.tags.map((tag, i) => (
                                        <span key={i} className="akv-tag-chip">{tag}</span>
                                    ))}
                                </div>
                            </div>
                        </div>

                        {/* Meta */}
                        <div className="akv-meta-row">
                            <span>Model: <strong>{data.llm_model}</strong></span>
                            <span>Cost: <strong>${data.cost_usd.toFixed(6)}</strong></span>
                            <span>Synthesized: <strong>{formatDate(data.synthesized_at)}</strong></span>
                        </div>
                    </div>
                )}

                {/* ── Timeline tab ── */}
                {activeTab === 'timeline' && (
                    <div className="akv-tab-content">
                        {data.knowledge_timeline.length === 0 ? (
                            <div className="akv-empty-state">No timeline data available.</div>
                        ) : (
                            <div className="akv-timeline">
                                {data.knowledge_timeline.map((entry, i) => (
                                    <div key={i} className="akv-tl-entry">
                                        {/* Left: time column */}
                                        <div className="akv-tl-time">
                                            <button
                                                type="button"
                                                className="akv-time-chip akv-time-chip--lg"
                                                onClick={() => onSeek?.(entry.start_sec)}
                                                title="Jump to segment"
                                            >
                                                {formatSeconds(entry.start_sec)}
                                            </button>
                                            <div className="akv-tl-duration">
                                                {formatSeconds(entry.end_sec - entry.start_sec)}
                                            </div>
                                        </div>

                                        {/* Connector */}
                                        <div className="akv-tl-connector">
                                            <div className="akv-tl-dot" />
                                            {i < data.knowledge_timeline.length - 1 && <div className="akv-tl-line" />}
                                        </div>

                                        {/* Right: content */}
                                        <div className="akv-tl-content">
                                            <div className="akv-tl-header">
                                                <div className="akv-tl-badges">
                                                    <span className="akv-badge akv-badge--gray">{entry.screen_type}</span>
                                                    <span className="akv-badge akv-badge--gray">{entry.event_type}</span>
                                                </div>
                                                <KnowledgeBar value={entry.knowledge_value} />
                                            </div>

                                            <p className="akv-tl-summary">{entry.activity_summary}</p>

                                            {entry.screen_content && (
                                                <div className="akv-tl-screen">
                                                    <Monitor size={10} />
                                                    <span>{entry.screen_content}</span>
                                                </div>
                                            )}

                                            {entry.spoken_content && (
                                                <div className="akv-tl-spoken">
                                                    <Mic size={10} />
                                                    <span>{entry.spoken_content}</span>
                                                </div>
                                            )}

                                            <div className="akv-tl-application">
                                                <TrendingUp size={10} />
                                                <span>{entry.application}</span>
                                            </div>

                                            <div className="akv-tl-tags">
                                                {entry.topics.map((t, j) => (
                                                    <span key={j} className="akv-tag-chip akv-tag-chip--sm">{t}</span>
                                                ))}
                                                {entry.keywords.map((k, j) => (
                                                    <span key={j} className="akv-kw-chip">{k}</span>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}

                {/* ── Workflow tab ── */}
                {activeTab === 'workflow' && (
                    <div className="akv-tab-content">
                        {data.workflow.length === 0 ? (
                            <div className="akv-empty-state">No workflow steps recorded.</div>
                        ) : (
                            <div className="akv-workflow">
                                {data.workflow.map((step) => (
                                    <div key={step.step} className="akv-wf-step">
                                        <div className="akv-wf-number">{step.step}</div>
                                        <div className="akv-wf-body">
                                            <p className="akv-wf-desc">{step.description}</p>
                                            <div className="akv-wf-time">
                                                <button
                                                    type="button"
                                                    className="akv-time-chip"
                                                    onClick={() => onSeek?.(step.start_sec)}
                                                >
                                                    <Clock size={9} />{formatSeconds(step.start_sec)}
                                                </button>
                                                <span className="akv-wf-arrow">→</span>
                                                <button
                                                    type="button"
                                                    className="akv-time-chip"
                                                    onClick={() => onSeek?.(step.end_sec)}
                                                >
                                                    <Clock size={9} />{formatSeconds(step.end_sec)}
                                                </button>
                                                <span className="akv-wf-dur">
                                                    ({formatSeconds(step.end_sec - step.start_sec)})
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}