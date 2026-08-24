import { useState } from 'react'
import { X } from 'lucide-react'
import { useEscapeToClose } from '../hooks/useEscapeToClose'
import { strings } from '../i18n/strings'

interface WorkspaceCreateModalProps {
  onClose: () => void
  onCreated: (workspaceId: string) => void
  onCreateWorkspace: (name: string) => Promise<{ id: string } | null>
}

export function WorkspaceCreateModal({ onClose, onCreated, onCreateWorkspace }: WorkspaceCreateModalProps) {
  const [name, setName] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [error, setError] = useState('')
  useEscapeToClose(onClose, !isCreating)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) {
      setError(strings.workspace.create.nameRequired)
      return
    }

    setIsCreating(true)
    setError('')

    try {
      const workspace = await onCreateWorkspace(name.trim())
      if (workspace) {
        onCreated(workspace.id)
      } else {
        setError(strings.workspace.create.createError)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : strings.workspace.create.createError)
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal workspace-create-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-area">
            <div className="modal-title">{strings.workspace.create.title}</div>
          </div>
          <button type="button" className="modal-close" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="form-group">
              <label htmlFor="workspace-name" className="form-label">
                {strings.workspace.create.nameLabel}
              </label>
              <input
                id="workspace-name"
                type="text"
                className="form-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={strings.workspace.create.namePlaceholder}
                autoFocus
                disabled={isCreating}
              />
            </div>
            {error && <div className="form-error">{error}</div>}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={isCreating}>
              {strings.workspace.create.cancelBtn}
            </button>
            <button type="submit" className="btn btn-primary" disabled={isCreating || !name.trim()}>
              {isCreating ? strings.workspace.create.creating : strings.workspace.create.createBtn}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
