import { memo } from 'react'
import type { NodeProps } from 'reactflow'
import { BaseNode } from './BaseNode'

type ActionNodeData = {
  label: string
  nodeType: string
  config?: Record<string, unknown>
  isConfigured?: boolean
}

export const ActionNode = memo(function ActionNode(props: NodeProps<ActionNodeData>) {
  return <BaseNode {...props} hasInput={true} hasOutput={true} />
})
