import { type AgentMessage, toolSemanticDescription, toolResultSummary } from '../hooks/useAgentStream'

interface ToolExecutionIndicatorProps {
    msg: AgentMessage
    onToggleThinking: (messageId: string) => void
}

export function ToolExecutionIndicator({ msg, onToggleThinking }: ToolExecutionIndicatorProps) {
    return (
        <div className="ask-ai-thinking-container">
            <div className="ask-ai-thinking">
                <span /><span /><span />
            </div>
            {msg.thinkingSteps && msg.thinkingSteps.length > 0 && (
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
                        <div className="ask-ai-thinking-steps">
                            {msg.thinkingSteps.map(step => (
                                <div key={step.id} className="ask-ai-thinking-step">
                                    {step.type === 'thinking' && step.text && (
                                        <div className="ask-ai-step-item ask-ai-step-thinking">
                                            <span className="ask-ai-step-badge">💭</span>
                                            <span className="ask-ai-step-text ask-ai-step-text-thinking">
                                                {step.text}
                                            </span>
                                        </div>
                                    )}
                                    {step.type === 'tool_start' && (
                                        <div className="ask-ai-step-item">
                                            <span className="ask-ai-step-badge">📌</span>
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
                                        </div>
                                    )}
                                    {step.type === 'tool_result' && (
                                        <div className="ask-ai-step-item">
                                            <span className="ask-ai-step-badge">{step.success === false ? '✗' : '✓'}</span>
                                            <span className="ask-ai-step-text">
                                                <strong>{step.toolName}</strong>
                                                <span className="ask-ai-step-detail"> {toolResultSummary(step.toolName ?? '', step.result, step.success !== false)}</span>
                                            </span>
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
