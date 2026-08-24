import { Zap, X } from 'lucide-react'
import { useEscapeToClose } from '../hooks/useEscapeToClose'
import { strings } from '../i18n/strings'

type ProcessAssetDialogProps = {
    assetTitle: string
    isLoading: boolean
    onProcess: () => void
    onSkip: () => void
}

export function ProcessAssetDialog({ assetTitle, isLoading, onProcess, onSkip }: ProcessAssetDialogProps) {
    // Overlay chỉ gọi onSkip khi không loading
    const handleOverlayClick = () => {
        if (!isLoading) onSkip();
    };
    useEscapeToClose(onSkip, !isLoading)
    return (
        <div className="pad-overlay" onClick={handleOverlayClick}>
            <div className="pad-box" onClick={e => e.stopPropagation()}>
                <div className="pad-close">
                    <button type="button" className="pad-close-btn" onClick={onSkip} disabled={isLoading}>
                        <X size={16} />
                    </button>
                </div>
                <div className="pad-icon">
                    <Zap size={32} />
                </div>
                <div className="pad-title">{strings.records.processDialog.title}</div>
                <div className="pad-body">
                    <p className="pad-name">{assetTitle}</p>
                    <p className="pad-desc">{strings.records.processDialog.desc}</p>
                </div>
                <div className="pad-actions">
                    <button type="button" className="pad-btn pad-btn--secondary" onClick={onSkip} disabled={isLoading}>
                        {strings.records.processDialog.skip}
                    </button>
                    <button type="button" className="pad-btn pad-btn--primary" onClick={onProcess} disabled={isLoading}>
                        {isLoading ? strings.records.processDialog.processing : strings.records.processDialog.processNow}
                    </button>
                </div>
            </div>
        </div>
    )
}
