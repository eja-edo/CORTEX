import type { TokenUsage } from '../services/api'

interface TokenBudgetBarProps {
    lastUsage: TokenUsage | null
    lastModelUsed: string | null
}

export function TokenBudgetBar({ lastUsage, lastModelUsed }: TokenBudgetBarProps) {
    if (!lastUsage) return null
    return (
        <div className="ask-ai-usage">
            <span className="ask-ai-usage-model">
                {lastModelUsed || 'Auto'}
            </span>
            <span className="ask-ai-usage-stat">↑ {lastUsage.prompt_tokens}</span>
            <span className="ask-ai-usage-stat">↓ {lastUsage.completion_tokens}</span>
            <span className="ask-ai-usage-stat ask-ai-usage-total">∑ {lastUsage.total_tokens}</span>
        </div>
    )
}
