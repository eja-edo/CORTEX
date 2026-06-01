import type { BlockNode } from '../../../types/editor'
import { ListBlock } from './ListBlock'

interface ListGroupBlockProps {
  block: BlockNode
}

interface FlatListItem {
  node: BlockNode
  depth: number
  order?: number
}

function flattenListItems(children: BlockNode[], depth: number): FlatListItem[] {
  const result: FlatListItem[] = []
  let orderedIndex = 0

  for (const child of children) {
    if (!child) continue

    if (child.type === 'ordered_list') {
      orderedIndex++
      result.push({ node: child, depth, order: orderedIndex })
    } else {
      result.push({ node: child, depth })
    }

    if (child.children) {
      for (const nested of child.children) {
        if (nested.type === 'list_group' && nested.children) {
          result.push(...flattenListItems(nested.children, depth + 1))
        }
      }
    }
  }

  return result
}

export function ListGroupBlock({ block }: ListGroupBlockProps) {
  const items = flattenListItems(block.children ?? [], 0)
  if (items.length === 0) return null

  return (
    <div className="block-list-group">
      {items.map(({ node, depth, order }) => (
        <ListBlock
          key={node.id}
          block={{
            ...node,
            meta: { ...node.meta, listNesting: depth },
          }}
          order={order}
        />
      ))}
    </div>
  )
}
