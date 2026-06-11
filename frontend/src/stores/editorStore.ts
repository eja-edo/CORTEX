import { create } from 'zustand'
import type { BlockNode, SlashMenuState, BubbleToolbarState } from '../types/editor'
import { parseMarkdownToBlocks } from '../utils/markdownParser'
import { serializeBlocksToMarkdown } from '../utils/markdownSerializer'

interface EditorStore {
  blocks: BlockNode[]
  focusedBlockId: string | null
  slashMenu: SlashMenuState
  bubbleToolbar: BubbleToolbarState
  noteId: string | null

  initializeFromMarkdown: (md: string, noteId?: string) => void
  setBlocks: (blocks: BlockNode[]) => void
  setNoteId: (noteId: string | null) => void

  setFocusedBlock: (blockId: string | null) => void
  updateBlockContent: (blockId: string, content: string) => void
  serializeAndNotify: (notify: (md: string) => void) => void

  splitBlock: (blockId: string, beforeContent: string, afterContent: string) => void
  deleteBlock: (blockId: string) => void
  mergeBlockBackward: (blockId: string) => void
  exitListOnEmpty: (blockId: string) => void

  openSlashMenu: (blockId: string, x: number, y: number) => void
  closeSlashMenu: () => void
  setSlashMenuSearch: (search: string) => void

  openBubbleToolbar: (x: number, y: number, start: number, end: number) => void
  closeBubbleToolbar: () => void

  insertBlockAfter: (afterId: string, type: BlockNode['type']) => void
  reorderBlock: (fromIndex: number, toIndex: number) => void
  serialize: () => string
}

let blockIdCounter = 0
function stableId(): string {
  blockIdCounter++
  return `block-${blockIdCounter}-${Date.now()}`
}

function isListItemType(type: BlockNode['type']): boolean {
  return type === 'bullet_list' || type === 'ordered_list' || type === 'task_list'
}

export const useEditorStore = create<EditorStore>((set, get) => ({
  blocks: [],
  focusedBlockId: null,
  slashMenu: { open: false, search: '', position: null, anchorBlockId: null },
  bubbleToolbar: { open: false, position: null, selection: null },
  noteId: null,

  initializeFromMarkdown: (md: string, noteId?: string) => {
    const blocks = parseMarkdownToBlocks(md)
    set({ blocks, focusedBlockId: null, noteId: noteId ?? null })
  },

  setBlocks: (blocks: BlockNode[]) => {
    set({ blocks })
  },

  setNoteId: (noteId: string | null) => {
    set({ noteId })
  },

  setFocusedBlock: (blockId: string | null) => {
    set({ focusedBlockId: blockId })
  },

  updateBlockContent: (blockId: string, content: string) => {
    const { blocks } = get()
    const updateRecursive = (list: BlockNode[]): boolean => {
      for (const b of list) {
        if (b.id === blockId) {
          b.content = content
          return true
        }
        if (b.children && updateRecursive(b.children)) return true
      }
      return false
    }
    const newBlocks = structuredClone(blocks)
    updateRecursive(newBlocks)
    set({ blocks: newBlocks })
  },

  serializeAndNotify: (notify: (md: string) => void) => {
    const { blocks } = get()
    const md = serializeBlocksToMarkdown(blocks)
    notify(md)
  },

  splitBlock: (blockId: string, beforeContent: string, afterContent: string) => {
    const { blocks } = get()
    let focusNextId: string | null = null

    const splitRecursive = (list: BlockNode[]): boolean => {
      for (let i = 0; i < list.length; i++) {
        const b = list[i]
        if (!b) continue
        if (b.id === blockId) {
          const nextType = isListItemType(b.type) ? b.type : 'paragraph'
          const nextMeta = isListItemType(b.type)
            ? { ...b.meta, checked: b.type === 'task_list' ? false : b.meta?.checked }
            : undefined
          const newBlock: BlockNode = {
            id: stableId(),
            type: nextType,
            content: afterContent,
            meta: nextMeta,
          }
          list[i] = { ...b, content: beforeContent }
          list.splice(i + 1, 0, newBlock)
          focusNextId = newBlock.id
          return true
        }
        if (b.children && splitRecursive(b.children!)) return true
      }
      return false
    }

    const newBlocks = structuredClone(blocks)
    splitRecursive(newBlocks)
    set({ blocks: newBlocks, focusedBlockId: focusNextId })
  },

  deleteBlock: (blockId: string) => {
    const { blocks } = get()
    const removeRecursive = (list: BlockNode[]): boolean => {
      for (let i = 0; i < list.length; i++) {
        if (list[i]?.id === blockId) {
          list.splice(i, 1)
          return true
        }
        if (list[i]?.children && removeRecursive(list[i].children!)) return true
      }
      return false
    }

    const newBlocks = structuredClone(blocks)
    removeRecursive(newBlocks)
    set({ blocks: newBlocks, focusedBlockId: null })
  },

  mergeBlockBackward: (blockId: string) => {
    const { blocks } = get()
    let mergedContent = ''
    let focusPrevId: string | null = null

    const mergeRecursive = (list: BlockNode[]): boolean => {
      for (let i = 0; i < list.length; i++) {
        if (list[i]?.id === blockId) {
          if (i > 0) {
            const prev = list[i - 1]!
            mergedContent = prev.content + (prev.content && list[i]!.content ? ' ' : '') + list[i]!.content
            focusPrevId = prev.id
            prev.content = mergedContent
            list.splice(i, 1)
          } else {
            // First block - just clear it
            list[i]!.content = ''
            focusPrevId = list[i]!.id
          }
          return true
        }
        if (list[i]?.children && mergeRecursive(list[i].children!)) return true
      }
      return false
    }

    const newBlocks = structuredClone(blocks)
    mergeRecursive(newBlocks)
    set({ blocks: newBlocks, focusedBlockId: focusPrevId })
  },

  exitListOnEmpty: (blockId: string) => {
    const { blocks } = get()
    let focusNextId: string | null = null

    const exitRecursive = (list: BlockNode[]): boolean => {
      for (let i = 0; i < list.length; i++) {
        const b = list[i]
        if (!b) continue

        if (b.type === 'list_group' && b.children) {
          const itemIndex = b.children.findIndex(child => child.id === blockId)
          if (itemIndex !== -1) {
            b.children.splice(itemIndex, 1)
            const paragraph: BlockNode = {
              id: stableId(),
              type: 'paragraph',
              content: '',
            }

            if (b.children.length === 0) {
              list.splice(i, 1, paragraph)
            } else {
              list.splice(i + 1, 0, paragraph)
            }

            focusNextId = paragraph.id
            return true
          }
        }

        if (b.children && exitRecursive(b.children)) return true
      }
      return false
    }

    const newBlocks = structuredClone(blocks)
    exitRecursive(newBlocks)
    set({ blocks: newBlocks, focusedBlockId: focusNextId })
  },

  openSlashMenu: (blockId: string, x: number, y: number) => {
    set({ slashMenu: { open: true, search: '', position: { x, y }, anchorBlockId: blockId } })
  },

  closeSlashMenu: () => {
    set({ slashMenu: { open: false, search: '', position: null, anchorBlockId: null } })
  },

  setSlashMenuSearch: (search: string) => {
    const { slashMenu } = get()
    set({ slashMenu: { ...slashMenu, search } })
  },

  openBubbleToolbar: (x: number, y: number, start: number, end: number) => {
    set({ bubbleToolbar: { open: true, position: { x, y }, selection: { start, end } } })
  },

  closeBubbleToolbar: () => {
    set({ bubbleToolbar: { open: false, position: null, selection: null } })
  },

  insertBlockAfter: (afterId: string, type: BlockNode['type']) => {
    const { blocks } = get()
    const newBlock: BlockNode = isListItemType(type)
      ? {
          id: stableId(),
          type: 'list_group',
          content: '',
          children: [
            {
              id: stableId(),
              type,
              content: '',
              meta: type === 'task_list' ? { checked: false } : undefined,
            },
          ],
        }
      : {
          id: stableId(),
          type,
          content: '',
        }

    const insertInList = (list: BlockNode[]): boolean => {
      for (let i = 0; i < list.length; i++) {
        if (list[i]?.id === afterId) {
          list.splice(i + 1, 0, newBlock)
          return true
        }
        if (list[i]?.children && insertInList(list[i].children!)) return true
      }
      return false
    }

    const newBlocks = structuredClone(blocks)
    if (!insertInList(newBlocks)) {
      newBlocks.push(newBlock)
    }

    const canFocus = type !== 'divider'
    const focusId = canFocus
      ? newBlock.type === 'list_group'
        ? newBlock.children?.[0]?.id ?? newBlock.id
        : newBlock.id
      : null

    set({
      blocks: newBlocks,
      focusedBlockId: focusId,
      slashMenu: { open: false, search: '', position: null, anchorBlockId: null },
    })
  },

  reorderBlock: (fromIndex: number, toIndex: number) => {
    const { blocks } = get()
    const newBlocks = structuredClone(blocks)
    const [moved] = newBlocks.splice(fromIndex, 1)
    if (moved) {
      newBlocks.splice(toIndex, 0, moved)
    }
    set({ blocks: newBlocks })
  },

  serialize: () => {
    const { blocks } = get()
    return serializeBlocksToMarkdown(blocks)
  },
}))
