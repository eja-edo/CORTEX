import { create } from 'zustand'
import type { BlockNode, SlashMenuState, BubbleToolbarState } from '../types/editor'
import { parseMarkdownToBlocks } from '../utils/markdownParser'
import { serializeBlocksToMarkdown } from '../utils/markdownSerializer'

interface EditorStore {
  blocks: BlockNode[]
  focusedBlockId: string | null
  slashMenu: SlashMenuState
  bubbleToolbar: BubbleToolbarState

  initializeFromMarkdown: (md: string) => void
  setBlocks: (blocks: BlockNode[]) => void

  setFocusedBlock: (blockId: string | null) => void
  updateBlockContent: (blockId: string, content: string) => void
  serializeAndNotify: (notify: (md: string) => void) => void

  splitBlock: (blockId: string, beforeContent: string, afterContent: string) => void
  deleteBlock: (blockId: string) => void
  mergeBlockBackward: (blockId: string) => void

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

export const useEditorStore = create<EditorStore>((set, get) => ({
  blocks: [],
  focusedBlockId: null,
  slashMenu: { open: false, search: '', position: null, anchorBlockId: null },
  bubbleToolbar: { open: false, position: null, selection: null },

  initializeFromMarkdown: (md: string) => {
    const blocks = parseMarkdownToBlocks(md)
    set({ blocks, focusedBlockId: null })
  },

  setBlocks: (blocks: BlockNode[]) => {
    set({ blocks })
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
    const { blocks, focusedBlockId } = get()
    const newBlock: BlockNode = {
      id: stableId(),
      type: 'paragraph',
      content: afterContent,
    }

    const splitRecursive = (list: BlockNode[]): boolean => {
      for (let i = 0; i < list.length; i++) {
        const b = list[i]
        if (!b) continue
        if (b.id === blockId) {
          list[i] = { ...b, content: beforeContent }
          list.splice(i + 1, 0, newBlock)
          return true
        }
        if (b.children && splitRecursive(b.children!)) return true
      }
      return false
    }

    const newBlocks = structuredClone(blocks)
    splitRecursive(newBlocks)
    set({ blocks: newBlocks, focusedBlockId: newBlock.id })
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
    const newBlock: BlockNode = {
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

    set({
      blocks: newBlocks,
      focusedBlockId: newBlock.id,
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
