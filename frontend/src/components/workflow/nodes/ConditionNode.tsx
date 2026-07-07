import { memo } from 'react'
import type { NodeProps } from 'reactflow'
import { BaseNode } from './BaseNode'

type ConditionNodeData = {
  label: string
  nodeType: string
  config?: Record<string, unknown>
  isConfigured?: boolean
}

export const ConditionNode = memo(function ConditionNode(props: NodeProps<ConditionNodeData>) {
  return <BaseNode {...props} hasInput={true} hasOutput={true} isCondition={true} />
})
