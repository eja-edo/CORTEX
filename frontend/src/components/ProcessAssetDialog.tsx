import { Zap, X } from 'lucide-react'

type ProcessAssetDialogProps = {
    assetTitle: string
    isLoading: boolean
    onProcess: () => void
    onSkip: () => void
}

export function ProcessAssetDialog({ assetTitle, isLoading, onProcess, onSkip }: ProcessAssetDialogProps) {
    return (
        <div className="pad-overlay" onClick={onSkip}>
            <div className="pad-box" onClick={e => e.stopPropagation()}>
                <div className="pad-close">
                    <button type="button" className="pad-close-btn" onClick={onSkip}>
                        <X size={16} />
                    </button>
                </div>
                <div className="pad-icon">
                    <Zap size={32} />
                </div>
                <div className="pad-title">Process Recording?</div>
                <div className="pad-body">
                    <p className="pad-name">{assetTitle}</p>
                    <p className="pad-desc">Extract transcript, text, and insights using AI analysis</p>
                </div>
                <div className="pad-actions">
                    <button type="button" className="pad-btn pad-btn--secondary" onClick={onSkip} disabled={isLoading}>
                        Skip
                    </button>
                    <button type="button" className="pad-btn pad-btn--primary" onClick={onProcess} disabled={isLoading}>
                        {isLoading ? 'Processing…' : 'Process Now'}
                    </button>
                </div>
            </div>
        </div>
    )
}
