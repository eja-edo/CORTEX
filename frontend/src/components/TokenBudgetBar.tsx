import type { TokenUsage } from '../services/api'
import { AVAILABLE_MODELS } from '../hooks/useAgentStream'

interface TokenBudgetBarProps {
    lastUsage: TokenUsage | null
    lastModelUsed: string | null
}

export function TokenBudgetBar({ lastUsage, lastModelUsed }: TokenBudgetBarProps) {
    if (!lastUsage) return null
    return (
        <div className="ask-ai-usage">
            <span className="ask-ai-usage-model">
                {lastModelUsed ? (AVAILABLE_MODELS.find(m => m.id === lastModelUsed)?.label || lastModelUsed) : 'Auto'}
            </span>
            <span className="ask-ai-usage-stat">↑ {lastUsage.prompt_tokens}</span>
            <span className="ask-ai-usage-stat">↓ {lastUsage.completion_tokens}</span>
            <span className="ask-ai-usage-stat ask-ai-usage-total">∑ {lastUsage.total_tokens}</span>
        </div>
    )
}
