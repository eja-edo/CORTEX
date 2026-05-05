import { AlertCircle, Check } from 'lucide-react'
import type { TokenBudgetStatus } from '../types'
import '../styles/token-budget.css'

interface TokenBudgetIndicatorProps {
    budgetStatus: TokenBudgetStatus | null
    isLoading?: boolean
    className?: string
}

export function TokenBudgetIndicator({ budgetStatus, isLoading = false, className = '' }: TokenBudgetIndicatorProps) {
    if (!budgetStatus || isLoading) {
        return (
            <div className={`token-budget-container ${className}`}>
                <div className="token-budget-skeleton">Loading...</div>
            </div>
        )
    }

    const percentage = budgetStatus.percentage
    const isWarning = percentage >= 80 && percentage < 100
    const isExceeded = percentage >= 100
    const isHealthy = percentage < 80

    const statusClass = isExceeded ? 'exceeded' : isWarning ? 'warning' : 'healthy'
    const statusLabel = isExceeded ? 'Limit reached' : isWarning ? 'Warning' : 'Healthy'
    const statusIcon = isExceeded ? <AlertCircle size={16} /> : isWarning ? <AlertCircle size={16} /> : <Check size={16} />

    return (
        <div className={`token-budget-container ${className}`}>
            <div className="token-budget-header">
                <span className="token-budget-label">Token Budget</span>
                <span className={`token-budget-status ${statusClass}`}>
                    {statusIcon}
                    {statusLabel}
                </span>
            </div>

            <div className="token-budget-bar-container">
                <div className="token-budget-bar">
                    <div
                        className={`token-budget-fill ${statusClass}`}
                        style={{ width: `${Math.min(percentage, 100)}%` }}
                        role="progressbar"
                        aria-valuenow={budgetStatus.used}
                        aria-valuemin={0}
                        aria-valuemax={budgetStatus.limit}
                    />
                </div>
            </div>

            <div className="token-budget-info">
                <div className="token-budget-text">
                    <span className="token-used">{budgetStatus.used.toLocaleString()}</span>
                    <span className="token-divider">/</span>
                    <span className="token-limit">{budgetStatus.limit.toLocaleString()}</span>
                </div>
                <div className="token-percentage">{percentage}%</div>
            </div>

            {isExceeded && (
                <div className="token-budget-message error">
                    You've reached your daily interaction limit. Please try again tomorrow.
                </div>
            )}

            {isWarning && (
                <div className="token-budget-message warning">
                    You're approaching your daily limit ({budgetStatus.remaining.toLocaleString()} tokens remaining).
                </div>
            )}
        </div>
    )
}
