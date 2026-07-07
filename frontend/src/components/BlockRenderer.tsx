import DOMPurify from 'dompurify'
import type { NotificationBlock, NotificationActionDef } from '../types'

type Props = {
  blocks: NotificationBlock[]
  actions?: NotificationActionDef[]
  onNavigate?: (url: string) => void
}

function Block({ block }: { block: NotificationBlock }) {
  switch (block.type) {
    case 'text':
      return <span className="notif-block-text">{block.text}</span>
    case 'image':
      return (
        <img
          className="notif-block-image"
          src={block.url}
          alt={block.alt ?? ''}
          loading="lazy"
        />
      )
    case 'html':
      return (
        <div
          className="notif-block-html"
          dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(block.html) }}
        />
      )
    case 'code':
      return (
        <pre className="notif-block-code">
          {block.language && <span className="notif-block-code-lang">{block.language}</span>}
          <code>{block.content}</code>
        </pre>
      )
    case 'markdown':
      return <span className="notif-block-text">{block.text}</span>
    default:
      return null
  }
}

export function BlockRenderer({ blocks, actions, onNavigate }: Props) {
  if (!blocks || blocks.length === 0) return null

  return (
    <div className="notif-blocks">
      {blocks.map((block, i) => (
        <div key={i} className={`notif-block notif-block-${block.type}`}>
          <Block block={block} />
        </div>
      ))}
      {actions && actions.length > 0 && (
        <div className="notif-actions">
          {actions.map((action, i) => (
            <button
              key={i}
              type="button"
              className="notif-action-btn"
              onClick={() => {
                if (action.action === 'navigate' && action.url && onNavigate) {
                  onNavigate(action.url)
                }
              }}
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
