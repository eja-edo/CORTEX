export type BlockType =
  | 'paragraph'
  | 'heading_1'
  | 'heading_2'
  | 'heading_3'
  | 'bullet_list'
  | 'ordered_list'
  | 'task_list'
  | 'blockquote'
  | 'code_block'
  | 'table'
  | 'image'
  | 'divider'
  | 'callout'
  | 'toggle'
  | 'mermaid'
  | 'html'

export interface BlockMeta {
  level?: number
  checked?: boolean
  language?: string
  collapsed?: boolean
  calloutType?: 'NOTE' | 'TIP' | 'WARNING' | 'IMPORTANT' | 'CAUTION'
  listNesting?: number
}

export interface BlockNode {
  id: string
  type: BlockType
  content: string
  children?: BlockNode[]
  meta?: BlockMeta
}

export interface SlashMenuState {
  open: boolean
  search: string
  position: { x: number; y: number } | null
  anchorBlockId: string | null
}

export interface BubbleToolbarState {
  open: boolean
  position: { x: number; y: number } | null
  selection: { start: number; end: number } | null
}

export interface BlockDragState {
  dragging: boolean
  fromIndex: number | null
}

export type SyntheticListenerMap = Record<string, (event: React.SyntheticEvent) => void>

export function generateBlockId(): string {
  return crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}
