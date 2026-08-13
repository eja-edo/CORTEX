import type { ComponentType } from 'react'
import type { TemplateVar } from './AutocompleteField'
import { CreateNoteConfig } from './CreateNoteConfig'
import { UpdateNoteConfig } from './UpdateNoteConfig'
import { CreateTaskConfig } from './CreateTaskConfig'
import { UpdateTaskConfig } from './UpdateTaskConfig'
import { SendNotificationConfig } from './SendNotificationConfig'
import { ScheduleConfig } from './ScheduleConfig'
import { CallAIConfig } from './CallAIConfig'
import { CallApiConfig } from './CallApiConfig'
import { ExtractHtmlConfig } from './ExtractHtmlConfig'
import { GetSchedulesConfig } from './GetSchedulesConfig'
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
  'action.create_task': CreateTaskConfig,
  'action.update_task': UpdateTaskConfig,
  'action.send_notification': SendNotificationConfig,
  'action.schedule': ScheduleConfig,
  'action.call_ai': CallAIConfig,
  'action.call_api': CallApiConfig,
  'action.extract_html': ExtractHtmlConfig,
  'action.get_schedules': GetSchedulesConfig,
  'action.wait': WaitConfig,
  'action.condition': ConditionConfig,
  'trigger.schedule': ScheduleTriggerConfig,
}

export function getConfigPanel(type: string): ComponentType<ConfigPanelProps> | null {
  return configPanels[type] ?? null
}

export type { TemplateVar }
