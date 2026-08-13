import { type ChangeEvent } from 'react'
import { Plus, Trash2 } from 'lucide-react'

type Props = {
  value: Record<string, string>
  onChange: (value: Record<string, string>) => void
  keyPlaceholder?: string
  valuePlaceholder?: string
  addLabel?: string
}

export function KeyValueTable({ value, onChange, keyPlaceholder = 'Key', valuePlaceholder = 'Value', addLabel = 'Add' }: Props) {
  const entries = Object.entries(value)

  const updateEntry = (index: number, key: string, val: string) => {
    const next = entries.map((entry, i) => (i === index ? [key, val] as [string, string] : entry))
    onChange(Object.fromEntries(next))
  }

  const removeEntry = (index: number) => {
    onChange(Object.fromEntries(entries.filter((_, i) => i !== index)))
  }

  const addEntry = () => {
    onChange(Object.fromEntries([...entries, ['', '']]))
  }

  return (
    <div className="wf-kv-table">
      {entries.map(([key, val], i) => (
        <div key={i} className="wf-kv-row">
          <input
            type="text"
            className="wf-config-input"
            placeholder={keyPlaceholder}
            value={key}
            onChange={(e: ChangeEvent<HTMLInputElement>) => updateEntry(i, e.target.value, val)}
          />
          <input
            type="text"
            className="wf-config-input"
            placeholder={valuePlaceholder}
            value={val}
            onChange={(e: ChangeEvent<HTMLInputElement>) => updateEntry(i, key, e.target.value)}
          />
          <button type="button" className="wf-kv-remove-btn" onClick={() => removeEntry(i)} title="Remove">
            <Trash2 size={13} />
          </button>
        </div>
      ))}
      <button type="button" className="wf-config-open-modal-btn" onClick={addEntry}>
        <Plus size={14} />
        {addLabel}
      </button>
    </div>
  )
}
