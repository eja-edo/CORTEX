import type { NodeTypes } from 'reactflow'
import { TriggerNode } from './TriggerNode'
import { ActionNode } from './ActionNode'
import { ConditionNode } from './ConditionNode'
import { StickyNoteNode } from './StickyNoteNode'

export const nodeTypes: NodeTypes = {
  'trigger.manual': TriggerNode,
  'trigger.schedule': TriggerNode,
  'trigger.webhook': TriggerNode,
  'trigger.internal_event': TriggerNode,
  'action.send_notification': ActionNode,
  'action.create_note': ActionNode,
  'action.schedule': ActionNode,
  'action.knowledge_search': ActionNode,
  'action.http_request': ActionNode,
  'action.condition': ConditionNode,
  'ai.analyze': ActionNode,
  'action.wait': ActionNode,
  'action.update_note': ActionNode,
  'action.call_ai': ActionNode,
  'action.call_webhook': ActionNode,
  'sticky_note': StickyNoteNode,
}
