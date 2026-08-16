import { uuid7 } from '../utils/uuid'

export type BlockType =
  | 'paragraph'
  | 'heading_1'
  | 'heading_2'
  | 'heading_3'
  | 'heading_4'
  | 'heading_5'
  | 'heading_6'
  | 'bullet_list'
  | 'ordered_list'
  | 'task_list'
  | 'list_group'
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
  order?: number
  lineStart?: number
  lineEnd?: number
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
  return uuid7()
}
