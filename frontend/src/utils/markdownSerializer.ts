import type { BlockNode } from '../types/editor'

function serializeListItem(
  item: BlockNode,
  prefix: string,
  indent: string,
): string {
  const content = item.content
  const header = `${indent}${prefix}${content}`
  let result = header

  if (item.children && item.children.length > 0) {
    result += '\n' + serializeBlocks(item.children, indent + '    ')
  }

  return result
}

function serializeBlocks(blocks: BlockNode[], baseIndent: string = ''): string {
  const output: string[] = []
  let orderedIndex = 0

  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i]
    if (!block) continue

    // Skip empty paragraph blocks at the top level
    if (block.type === 'paragraph' && block.content === '' && baseIndent === '') {
      continue
    }

    if (block.type !== 'ordered_list') {
      orderedIndex = 0
    }

    switch (block.type) {
      case 'paragraph': {
        output.push(`${baseIndent}${block.content}`)
        break
      }

      case 'heading_1':
      case 'heading_2':
      case 'heading_3': {
        const level = Number(block.type.split('_')[1])
        output.push(`${baseIndent}${'#'.repeat(level)} ${block.content}`)
        break
      }

      case 'bullet_list': {
        const prefix = block.meta?.checked !== undefined
          ? `- [${block.meta.checked ? 'x' : ' '}] `
          : '- '
        output.push(serializeListItem(block, prefix, baseIndent))
        break
      }

      case 'ordered_list': {
        orderedIndex += 1
        const prefix = `${orderedIndex}. `
        output.push(serializeListItem(block, prefix, baseIndent))
        break
      }

      case 'task_list': {
        const checked = block.meta?.checked ?? false
        const prefix = `- [${checked ? 'x' : ' '}] `
        output.push(serializeListItem(block, prefix, baseIndent))
        break
      }

      case 'list_group': {
        orderedIndex = 0
        if (block.children && block.children.length > 0) {
          let groupOrderedIndex = 1
          for (const child of block.children) {
            if (!child) continue
            if (child.type === 'ordered_list') {
              output.push(serializeListItem(child, `${groupOrderedIndex}. `, baseIndent))
              groupOrderedIndex++
              continue
            }
            if (child.type === 'task_list') {
              const checked = child.meta?.checked ?? false
              output.push(serializeListItem(child, `- [${checked ? 'x' : ' '}] `, baseIndent))
              continue
            }
            output.push(serializeListItem(child, '- ', baseIndent))
          }
        }
        break
      }

      case 'blockquote': {
        if (block.children && block.children.length > 0) {
          for (const child of block.children) {
            const childLines = serializeBlocks([child], baseIndent)
              .split('\n')
              .filter(Boolean)
            for (const line of childLines) {
              output.push(`${baseIndent}> ${line}`)
            }
          }
        } else if (block.content) {
          output.push(`${baseIndent}> ${block.content}`)
        }
        break
      }

      case 'code_block': {
        const lang = block.meta?.language ?? ''
        output.push(`${baseIndent}\`\`\`${lang}`)
        output.push(`${baseIndent}${block.content}`)
        output.push(`${baseIndent}\`\`\``)
        break
      }

      case 'table': {
        output.push(`${baseIndent}${block.content}`)
        break
      }

      case 'divider': {
        output.push(`${baseIndent}---`)
        break
      }

      case 'image': {
        output.push(`${baseIndent}${block.content}`)
        break
      }

      case 'callout': {
        const calloutType = block.meta?.calloutType ?? 'NOTE'
        const lines = block.content.split('\n')
        output.push(`${baseIndent}> [!${calloutType}]`)
        for (const line of lines) {
          output.push(`${baseIndent}> ${line}`)
        }
        break
      }

      case 'toggle': {
        output.push(`${baseIndent}<details>`)
        output.push(`${baseIndent}<summary>${block.content}</summary>`)
        output.push('')
        if (block.children && block.children.length > 0) {
          const childMd = serializeBlocks(block.children)
          for (const line of childMd.split('\n')) {
            output.push(`${baseIndent}${line}`)
          }
        }
        output.push('')
        output.push(`${baseIndent}</details>`)
        break
      }

      case 'mermaid': {
        output.push(`${baseIndent}\`\`\`mermaid`)
        output.push(`${baseIndent}${block.content}`)
        output.push(`${baseIndent}\`\`\``)
        break
      }

      case 'html': {
        output.push(`${baseIndent}${block.content}`)
        break
      }

      default: {
        output.push(`${baseIndent}${block.content}`)
      }
    }


  }

  return output.join('\n')
}

export function serializeBlocksToMarkdown(blocks: BlockNode[]): string {
  return serializeBlocks(blocks)
}