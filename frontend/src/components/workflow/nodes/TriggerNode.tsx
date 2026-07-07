import { memo } from 'react'
import type { NodeProps } from 'reactflow'
import { BaseNode } from './BaseNode'

type TriggerNodeData = {
  label: string
  nodeType: string
  config?: Record<string, unknown>
  isConfigured?: boolean
}

export const TriggerNode = memo(function TriggerNode(props: NodeProps<TriggerNodeData>) {
  return <BaseNode {...props} hasInput={false} hasOutput={true} isTrigger={true} />
})
