import { useState } from 'react'

type VariableGroup = {
  label: string
  variables: string[]
}

const GROUPS: VariableGroup[] = [
  {
    label: 'Trigger',
    variables: ['{{trigger.id}}', '{{trigger.type}}', '{{trigger.event}}', '{{trigger.title}}', '{{trigger.body}}', '{{trigger.user_id}}', '{{trigger.note_id}}', '{{trigger.schedule_id}}', '{{trigger.start_time}}'],
  },
  {
    label: 'Previous Steps',
    variables: ['{{steps.NODE_ID.result}}', '{{steps.NODE_ID.status}}', '{{steps.NODE_ID.error}}'],
  },
]

type Props = {
  onInsert: (variable: string) => void
}

export function TemplateHelper({ onInsert }: Props) {
  const [open, setOpen] = useState(false)

  return (
    <div className="wf-template-helper" style={{ position: 'relative' }}>
      <button
        type="button"
        className="wf-template-helper-btn"
        onClick={() => setOpen(!open)}
        title="Insert template variable"
      >
        {`{x}`}
      </button>
      {open && (
        <div className="wf-template-helper-dropdown">
          {GROUPS.map(group => (
            <div key={group.label}>
              <div className="wf-template-helper-group-label">{group.label}</div>
              {group.variables.map(v => (
                <button
                  key={v}
                  type="button"
                  className="wf-template-helper-item"
                  onClick={() => {
                    onInsert(v)
                    setOpen(false)
                  }}
                >
                  {v}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
