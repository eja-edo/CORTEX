import type { ComponentType } from 'react'
import type { TemplateVar } from './AutocompleteField'
import { CreateNoteConfig } from './CreateNoteConfig'
import { UpdateNoteConfig } from './UpdateNoteConfig'
import { SendNotificationConfig } from './SendNotificationConfig'
import { ScheduleConfig } from './ScheduleConfig'
import { CallAIConfig } from './CallAIConfig'
import { CallWebhookConfig } from './CallWebhookConfig'
import { WaitConfig } from './WaitConfig'
import { ConditionConfig } from './ConditionConfig'
import { ScheduleTriggerConfig } from './ScheduleTriggerConfig'

export type ConfigPanelProps = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
  templateVars?: TemplateVar[]
}

const configPanels: Record<string, ComponentType<ConfigPanelProps>> = {
  'action.create_note': CreateNoteConfig,
  'action.update_note': UpdateNoteConfig,
  'action.send_notification': SendNotificationConfig,
  'action.schedule': ScheduleConfig,
  'action.call_ai': CallAIConfig,
  'action.call_webhook': CallWebhookConfig,
  'action.wait': WaitConfig,
  'action.condition': ConditionConfig,
  'trigger.schedule': ScheduleTriggerConfig,
}

export function getConfigPanel(type: string): ComponentType<ConfigPanelProps> | null {
  return configPanels[type] ?? null
}

export type { TemplateVar }
