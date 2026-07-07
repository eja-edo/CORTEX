import type { BlockNode } from '../../../types/editor'
import { BlockRenderer } from '../BlockRenderer'

interface BlockquoteBlockProps {
  block: BlockNode
}

export function BlockquoteBlock({ block }: BlockquoteBlockProps) {
  const hasChildren = block.children && block.children.length > 0

  return (
    <div className="block-blockquote">
      {hasChildren ? (
        <div className="block-blockquote-children">
          {block.children!.map(child => (
            <BlockRenderer key={child.id} block={child} />
          ))}
        </div>
      ) : (
        <p className="block-blockquote-text">{block.content}</p>
      )}
    </div>
  )
}