import type { Tone } from '../components/ui'
import type { AiState } from './api'

export const input = 'h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm font-normal'
export const codeInput = `${input} text-center font-mono text-lg tracking-[0.4em]`
export const AI_LABEL: Record<AiState, [string, Tone]> = {
  running: ['AI đang chạy', 'ok'], paused: ['AI tạm dừng', 'bad'], partial: ['Dừng một phần', 'warn'], none: ['Chưa có sandbox', 'neutral'],
}
