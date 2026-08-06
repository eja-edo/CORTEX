import { type AgentMessage, toolSemanticDescription, toolResultSummary } from '../hooks/useAgentStream'

type Step = NonNullable<AgentMessage['thinkingSteps']>[number]

interface ToolExecutionIndicatorProps {
    msg: AgentMessage
    onToggleThinking: (messageId: string) => void
}

function dotTone(step: Step, isLast: boolean, loading: boolean): string {
    if (step.type === 'tool_result') {
        return step.success === false ? 'error' : 'success'
    }
    if (isLast && loading) return 'active'
    return 'muted'
}

export function ToolExecutionIndicator({ msg, onToggleThinking }: ToolExecutionIndicatorProps) {
    const steps = msg.thinkingSteps ?? []
    const timelineSteps = steps.filter(s => s.type !== 'text')

    return (
        <div className="ask-ai-thinking-container">
            {timelineSteps.length === 0 && (
                <div className="ask-ai-thinking">
                    <span /><span /><span />
                </div>
            )}
            {timelineSteps.length > 0 && (
                <div className="ask-ai-thinking-wrapper">
                    <button
                        type="button"
                        className="ask-ai-thinking-toggle"
                        onClick={() => onToggleThinking(msg.id)}
                    >
                        {msg.loading ? 'Thinking' : 'Thoughts'}
                        <span className={`ask-ai-thinking-toggle-icon ${msg.thinkingOpen ? 'open' : ''}`}>
                            ▾
                        </span>
                    </button>
                    {msg.thinkingOpen && (
                        <div className="ask-ai-timeline">
                            {timelineSteps.map((step, i) => {
                                const tone = dotTone(step, i === timelineSteps.length - 1, !!msg.loading)
                                return (
                                    <div key={step.id} className="ask-ai-timeline-step">
                                        <span className={`ask-ai-timeline-dot ask-ai-timeline-dot--${tone}`} />
                                        {step.type === 'thinking' && step.text && (
                                            <span className="ask-ai-step-text ask-ai-step-text-thinking">
                                                {step.text}
                                            </span>
                                        )}
                                        {step.type === 'tool_start' && (
                                            <span className="ask-ai-step-text">
                                                <strong>{step.toolName}</strong>
                                                <span className="ask-ai-step-detail"> → {toolSemanticDescription(step.toolName ?? '', step.toolArgs)}</span>
                                                {step.toolArgs && Object.keys(step.toolArgs).length > 0 && (
                                                    <details>
                                                        <summary style={{ fontSize: '11px', cursor: 'pointer', color: 'var(--text-tertiary)' }}>chi tiết</summary>
                                                        <code style={{ marginLeft: '4px', fontSize: '11px' }}>
                                                            {JSON.stringify(step.toolArgs, null, 2).slice(0, 200)}
                                                            {JSON.stringify(step.toolArgs).length > 200 ? '…' : ''}
                                                        </code>
                                                    </details>
                                                )}
                                            </span>
                                        )}
                                        {step.type === 'tool_result' && (
                                            <span className="ask-ai-step-text">
                                                <strong>{step.toolName}</strong>
                                                <span className="ask-ai-step-detail"> {toolResultSummary(step.toolName ?? '', step.result, step.success !== false)}</span>
                                            </span>
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
