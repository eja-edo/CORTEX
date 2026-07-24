import type { BlockNode } from '../../types/editor'
import type { SyntheticListenerMap } from '../../types/editor'
import { BlockWrapper } from './BlockWrapper'
import { ParagraphBlock } from './blocks/ParagraphBlock'
import { HeadingBlock } from './blocks/HeadingBlock'
import { ListBlock } from './blocks/ListBlock'
import { ListGroupBlock } from './blocks/ListGroupBlock'
import { CodeBlock } from './blocks/CodeBlock'
import { BlockquoteBlock } from './blocks/BlockquoteBlock'
import { TableBlock } from './blocks/TableBlock'
import { DividerBlock } from './blocks/DividerBlock'
import { ImageBlock } from './blocks/ImageBlock'
import { CalloutBlock } from './blocks/CalloutBlock'
import { ToggleBlock } from './blocks/ToggleBlock'
import { MermaidBlock } from './blocks/MermaidBlock'

interface BlockRendererProps {
  block: BlockNode
  dragHandleListeners?: SyntheticListenerMap
}

export function BlockRenderer({ block, dragHandleListeners }: BlockRendererProps) {
  const renderContent = () => {
    switch (block.type) {
      case 'paragraph':
        return <ParagraphBlock block={block} />

      case 'heading_1':
      case 'heading_2':
      case 'heading_3':
      case 'heading_4':
      case 'heading_5':
      case 'heading_6':
        return <HeadingBlock block={block} />

      case 'bullet_list':
      case 'ordered_list':
      case 'task_list':
        return <ListBlock block={block} />

      case 'list_group':
        return <ListGroupBlock block={block} />

      case 'code_block':
        return <CodeBlock block={block} />

      case 'blockquote':
        return <BlockquoteBlock block={block} />

      case 'table':
        return <TableBlock block={block} />

      case 'divider':
        return <DividerBlock />

      case 'image':
        return <ImageBlock block={block} />

      case 'callout':
        return <CalloutBlock block={block} />

      case 'toggle':
        return <ToggleBlock block={block} />

      case 'mermaid':
        return <MermaidBlock block={block} />

      case 'html':
        return <div className="block-html" dangerouslySetInnerHTML={{ __html: block.content }} />

      default:
        return <div className="block-unknown">{block.content}</div>
    }
  }

  if (block.type === 'divider') {
    return (
      <BlockWrapper block={block} dragHandleListeners={dragHandleListeners}>
        <DividerBlock />
      </BlockWrapper>
    )
  }

  return (
    <BlockWrapper block={block} dragHandleListeners={dragHandleListeners}>
      {renderContent()}
    </BlockWrapper>
  )
}
