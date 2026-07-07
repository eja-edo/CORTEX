import { ArrowLeft, Save, Play, Pause, PlayCircle, Trash2 } from 'lucide-react'

type WorkflowStatus = 'draft' | 'active' | 'paused' | 'archived'

type StatusBadge = {
  label: string
  color: string
}

type WorkflowToolbarProps = {
  workflowName: string
  workflowStatus: WorkflowStatus
  currentWorkflowId: string | null
  saving: boolean
  statusBadge: StatusBadge
  onNameChange: (name: string) => void
  onBack: () => void
  onSave: () => void
  onActivate: () => void
  onPause: () => void
  onRun: () => void
  onDelete: () => void
}

export function WorkflowToolbar({
  workflowName,
  workflowStatus,
  currentWorkflowId,
  saving,
  statusBadge,
  onNameChange,
  onBack,
  onSave,
  onActivate,
  onPause,
  onRun,
  onDelete,
}: WorkflowToolbarProps) {
  return (
    <div className="wf-toolbar">
      <div className="wf-toolbar-left">
        <button type="button" className="wf-toolbar-back-btn" onClick={onBack} title="Back">
          <ArrowLeft size={18} />
        </button>
        <div className="wf-toolbar-title-area">
          <input
            type="text"
            className="wf-name-input"
            value={workflowName}
            onChange={e => onNameChange(e.target.value)}
            placeholder="Workflow name..."
          />
          <div className="wf-toolbar-badges">
            <span className="wf-status-badge" style={{ background: statusBadge.color === 'var(--green)' ? 'rgba(15,123,108,0.1)' : statusBadge.color === 'var(--yellow)' ? 'rgba(223,171,1,0.12)' : 'var(--bg-active)', color: statusBadge.color === 'var(--green)' ? 'var(--green)' : statusBadge.color === 'var(--yellow)' ? 'var(--yellow)' : 'var(--text-tertiary)' }}>
              {statusBadge.label}
            </span>
          </div>
        </div>
      </div>
      <div className="wf-toolbar-right">
        <button type="button" className="wf-toolbar-btn" onClick={onSave} disabled={saving}>
          <Save size={14} />
          {saving ? 'Saving...' : 'Save'}
        </button>
        {workflowStatus === 'draft' && (
          <button type="button" className="wf-toolbar-btn-primary" onClick={onActivate}>
            <PlayCircle size={15} />
            Activate
          </button>
        )}
        {workflowStatus === 'active' && (
          <>
            <button type="button" className="wf-toolbar-btn" onClick={onPause}>
              <Pause size={14} />
              Pause
            </button>
            <button type="button" className="wf-toolbar-btn-primary" onClick={onRun}>
              <Play size={15} />
              Run
            </button>
          </>
        )}
        {(workflowStatus === 'paused' || workflowStatus === 'archived') && (
          <button type="button" className="wf-toolbar-btn-primary" onClick={onActivate}>
            <PlayCircle size={15} />
            {workflowStatus === 'paused' ? 'Resume' : 'Reactivate'}
          </button>
        )}
        {currentWorkflowId && (
          <button type="button" className="wf-toolbar-btn-danger" onClick={onDelete}>
            <Trash2 size={14} />
            Delete
          </button>
        )}
      </div>
    </div>
  )
}
