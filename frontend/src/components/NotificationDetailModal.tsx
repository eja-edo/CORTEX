import { Trash2, X } from 'lucide-react'
import { useEscapeToClose } from '../hooks/useEscapeToClose'
import { BlockRenderer } from './BlockRenderer'
import type { NotificationBlock, NotificationActionDef } from '../types'

type NotificationDetailModalProps = {
    title: string
    timestamp: Date
    body?: string | null
    content?: NotificationBlock[]
    actions?: NotificationActionDef[]
    /** `payload.navigate_to` — some notifications carry a click-through
     * target with no explicit action buttons attached. */
    navigateTo?: string
    onClose: () => void
    onNavigate?: (path: string) => void
    onDelete?: () => void
}

export function NotificationDetailModal({
    title,
    timestamp,
    body,
    content,
    actions,
    navigateTo,
    onClose,
    onNavigate,
    onDelete,
}: NotificationDetailModalProps) {
    useEscapeToClose(onClose)
    return (
        <div className="modal-backdrop" onClick={onClose}>
            <div className="modal notifications-detail-modal" onClick={(e) => e.stopPropagation()}>
                <div className="modal-header">
                    <div className="modal-title-area">
                        <h2 className="notifications-detail-title">{title}</h2>
                        <span className="notifications-detail-time">{timestamp.toLocaleString('vi-VN')}</span>
                    </div>
                    <button type="button" className="notifications-toolbar-btn" onClick={onClose} aria-label="Đóng">
                        <X size={16} />
                    </button>
                </div>
                <div className="notifications-detail-body">
                    {content && content.length > 0 ? (
                        <BlockRenderer blocks={content} actions={actions} onNavigate={onNavigate} />
                    ) : body ? (
                        <p className="notifications-detail-text">{body}</p>
                    ) : null}
                </div>
                {(navigateTo || onDelete) && (
                    <div className="notifications-detail-footer">
                        {navigateTo && onNavigate && (
                            <button
                                type="button"
                                className="notifications-toolbar-btn"
                                onClick={() => onNavigate(navigateTo)}
                            >
                                Xem chi tiết
                            </button>
                        )}
                        {onDelete && (
                            <button type="button" className="notifications-toolbar-btn danger" onClick={onDelete}>
                                <Trash2 size={15} />
                                <span>Xoá</span>
                            </button>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
