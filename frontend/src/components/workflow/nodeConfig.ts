import {
  Hand,
  Clock,
  Webhook,
  Bell,
  FileText,
  Calendar,
  Search,
  ExternalLink,
  GitBranch,
  Brain,
  Timer,
  Pencil,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'

export type NodeCategory = 'trigger' | 'action' | 'ai' | 'condition' | 'wait' | 'webhook'

export type NodeConfig = {
  type: string
  label: string
  category: NodeCategory
  icon: LucideIcon
  color: string
  bgVar: string
  hasInput: boolean
  hasOutput: boolean
  isCondition?: boolean
  description: string
}

export const NODE_CONFIGS: NodeConfig[] = [
  {
    type: 'trigger.manual',
    label: 'Manual',
    category: 'trigger',
    icon: Hand,
    color: 'var(--wf-trigger)',
    bgVar: 'var(--wf-trigger-bg)',
    hasInput: false,
    hasOutput: true,
    description: 'Run workflow manually',
  },
  {
    type: 'trigger.schedule',
    label: 'Schedule',
    category: 'trigger',
    icon: Clock,
    color: 'var(--wf-trigger)',
    bgVar: 'var(--wf-trigger-bg)',
    hasInput: false,
    hasOutput: true,
    description: 'Run on a schedule',
  },
  {
    type: 'trigger.webhook',
    label: 'Webhook',
    category: 'webhook',
    icon: Webhook,
    color: 'var(--wf-webhook)',
    bgVar: 'var(--wf-webhook-bg)',
    hasInput: false,
    hasOutput: true,
    description: 'Run via webhook call',
  },
  {
    type: 'trigger.internal_event',
    label: 'Internal Event',
    category: 'trigger',
    icon: Bell,
    color: 'var(--wf-trigger)',
    bgVar: 'var(--wf-trigger-bg)',
    hasInput: false,
    hasOutput: true,
    description: 'React to internal events',
  },
  {
    type: 'action.send_notification',
    label: 'Send Notification',
    category: 'action',
    icon: Bell,
    color: 'var(--wf-action)',
    bgVar: 'var(--wf-action-bg)',
    hasInput: true,
    hasOutput: true,
    description: 'Send a push notification',
  },
  {
    type: 'action.create_note',
    label: 'Create Note',
    category: 'action',
    icon: FileText,
    color: 'var(--wf-action)',
    bgVar: 'var(--wf-action-bg)',
    hasInput: true,
    hasOutput: true,
    description: 'Create a new note',
  },
  {
    type: 'action.schedule',
    label: 'Create Schedule',
    category: 'action',
    icon: Calendar,
    color: 'var(--wf-action)',
    bgVar: 'var(--wf-action-bg)',
    hasInput: true,
    hasOutput: true,
    description: 'Create a calendar event',
  },
  {
    type: 'action.knowledge_search',
    label: 'Knowledge Search',
    category: 'ai',
    icon: Search,
    color: 'var(--wf-ai)',
    bgVar: 'var(--wf-ai-bg)',
    hasInput: true,
    hasOutput: true,
    description: 'Search knowledge base',
  },
  {
    type: 'action.http_request',
    label: 'HTTP Request',
    category: 'action',
    icon: ExternalLink,
    color: 'var(--wf-action)',
    bgVar: 'var(--wf-action-bg)',
    hasInput: true,
    hasOutput: true,
    description: 'Make an HTTP request',
  },
  {
    type: 'action.condition',
    label: 'Condition',
    category: 'condition',
    icon: GitBranch,
    color: 'var(--wf-condition)',
    bgVar: 'var(--wf-condition-bg)',
    hasInput: true,
    hasOutput: true,
    isCondition: true,
    description: 'Branch based on conditions',
  },
  {
    type: 'ai.analyze',
    label: 'AI Analyze',
    category: 'ai',
    icon: Brain,
    color: 'var(--wf-ai)',
    bgVar: 'var(--wf-ai-bg)',
    hasInput: true,
    hasOutput: true,
    description: 'AI-powered analysis',
  },
  {
    type: 'action.wait',
    label: 'Wait',
    category: 'wait',
    icon: Timer,
    color: 'var(--wf-wait)',
    bgVar: 'var(--wf-wait-bg)',
    hasInput: true,
    hasOutput: true,
    description: 'Wait before continuing',
  },
  {
    type: 'action.update_note',
    label: 'Update Note',
    category: 'action',
    icon: Pencil,
    color: 'var(--wf-action)',
    bgVar: 'var(--wf-action-bg)',
    hasInput: true,
    hasOutput: true,
    description: 'Update an existing note',
  },
  {
    type: 'action.call_ai',
    label: 'Call AI',
    category: 'ai',
    icon: Sparkles,
    color: 'var(--wf-ai)',
    bgVar: 'var(--wf-ai-bg)',
    hasInput: true,
    hasOutput: true,
    description: 'Send a prompt to AI for completion',
  },
  {
    type: 'action.call_webhook',
    label: 'Call Webhook',
    category: 'webhook',
    icon: Webhook,
    color: 'var(--wf-webhook)',
    bgVar: 'var(--wf-webhook-bg)',
    hasInput: true,
    hasOutput: true,
    description: 'Call an external webhook',
  },
]

export function getNodeConfig(type: string): NodeConfig | undefined {
  return NODE_CONFIGS.find(c => c.type === type)
}

export function getNodeColor(type: string): string {
  return getNodeConfig(type)?.color ?? 'var(--text-tertiary)'
}

export function isTriggerType(type: string): boolean {
  const config = getNodeConfig(type)
  return config?.category === 'trigger' || config?.category === 'webhook'
}