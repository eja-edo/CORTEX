import { useState } from 'react'
import { X } from 'lucide-react'

interface WorkspaceCreateModalProps {
  onClose: () => void
  onCreated: (workspaceId: string) => void
  onCreateWorkspace: (name: string) => Promise<{ id: string } | null>
}

export function WorkspaceCreateModal({ onClose, onCreated, onCreateWorkspace }: WorkspaceCreateModalProps) {
  const [name, setName] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) {
      setError('Workspace name is required')
      return
    }

    setIsCreating(true)
    setError('')

    try {
      const workspace = await onCreateWorkspace(name.trim())
      if (workspace) {
        onCreated(workspace.id)
      } else {
        setError('Failed to create workspace')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create workspace')
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal workspace-create-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-area">
            <div className="modal-title">Create Workspace</div>
          </div>
          <button type="button" className="modal-close" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="form-group">
              <label htmlFor="workspace-name" className="form-label">
                Workspace Name
              </label>
              <input
                id="workspace-name"
                type="text"
                className="form-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Team Project, Personal Notes"
                autoFocus
                disabled={isCreating}
              />
              {error && <div className="form-error">{error}</div>}
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={isCreating}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={isCreating || !name.trim()}>
              {isCreating ? 'Creating...' : 'Create Workspace'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
