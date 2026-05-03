import { useState } from 'react'
import { X, Shield, Users, Eye, UserPlus, Trash2 } from 'lucide-react'

interface WorkspaceMember {
  id: string
  user_id: string
  email: string
  full_name: string | null
  role: 'owner' | 'editor' | 'viewer'
}

interface WorkspaceMembersModalProps {
  workspace: { id: string; name: string; is_personal: boolean }
  members: WorkspaceMember[]
  onClose: () => void
  onAddMember: (email: string, role: 'editor' | 'viewer') => Promise<boolean>
  onRemoveMember: (userId: string) => Promise<boolean>
  onChangeRole: (userId: string, role: 'editor' | 'viewer') => Promise<boolean>
}

export function WorkspaceMembersModal({
  workspace,
  members,
  onClose,
  onAddMember,
  onRemoveMember,
  onChangeRole,
}: WorkspaceMembersModalProps) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'editor' | 'viewer'>('editor')
  const [isAdding, setIsAdding] = useState(false)
  const [error, setError] = useState('')

  const handleAddMember = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim()) {
      setError('Email is required')
      return
    }

    setIsAdding(true)
    setError('')

    try {
      const success = await onAddMember(email.trim(), role)
      if (success) {
        setEmail('')
      } else {
        setError('Failed to add member')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add member')
    } finally {
      setIsAdding(false)
    }
  }

  const getRoleIcon = (role: string) => {
    switch (role) {
      case 'owner':
        return <Shield size={14} />
      case 'editor':
        return <Users size={14} />
      case 'viewer':
        return <Eye size={14} />
      default:
        return null
    }
  }

  const getRoleBadgeColor = (role: string) => {
    switch (role) {
      case 'owner':
        return { bg: '#f2f9ff', text: '#097fe8' }
      case 'editor':
        return { bg: '#f0faf0', text: '#1aae39' }
      case 'viewer':
        return { bg: '#f6f5f4', text: '#615d59' }
      default:
        return { bg: '#f6f5f4', text: '#615d59' }
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal workspace-members-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-area">
            <div className="modal-title">Manage Members — {workspace.name}</div>
          </div>
          <button type="button" className="modal-close" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="modal-body">
          {/* Add Member Form */}
          {!workspace.is_personal && (
            <form onSubmit={handleAddMember} className="add-member-form">
              <div className="form-group">
                <label htmlFor="member-email" className="form-label">
                  Add Member by Email
                </label>
                <div className="add-member-inputs">
                  <input
                    id="member-email"
                    type="email"
                    className="form-input"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="user@example.com"
                    disabled={isAdding}
                  />
                  <select
                    className="form-select"
                    value={role}
                    onChange={(e) => setRole(e.target.value as 'editor' | 'viewer')}
                    disabled={isAdding}
                  >
                    <option value="editor">Editor</option>
                    <option value="viewer">Viewer</option>
                  </select>
                  <button type="submit" className="btn btn-primary" disabled={isAdding || !email.trim()}>
                    <UserPlus size={14} />
                    <span>{isAdding ? 'Adding...' : 'Add'}</span>
                  </button>
                </div>
                {error && <div className="form-error">{error}</div>}
              </div>
            </form>
          )}

          {/* Members List */}
          <div className="members-list">
            <div className="members-list-header">
              <span>Members ({members.length})</span>
            </div>
            {members.length === 0 ? (
              <div className="members-empty">No members yet</div>
            ) : (
              members.map((member) => (
                <div key={member.user_id} className="member-item">
                  <div className="member-info">
                    <div className="member-avatar">
                      {member.full_name?.charAt(0).toUpperCase() || member.email.charAt(0).toUpperCase()}
                    </div>
                    <div className="member-details">
                      <div className="member-name">{member.full_name || member.email}</div>
                      {member.full_name && <div className="member-email">{member.email}</div>}
                    </div>
                  </div>
                  <div className="member-actions">
                    <span
                      className="member-role-badge"
                      style={{
                        background: getRoleBadgeColor(member.role).bg,
                        color: getRoleBadgeColor(member.role).text,
                      }}
                    >
                      {getRoleIcon(member.role)}
                      <span>{member.role}</span>
                    </span>
                    {!workspace.is_personal && member.role !== 'owner' && (
                      <>
                        <select
                          className="member-role-select"
                          value={member.role}
                          onChange={(e) => onChangeRole(member.user_id, e.target.value as 'editor' | 'viewer')}
                        >
                          <option value="editor">Editor</option>
                          <option value="viewer">Viewer</option>
                        </select>
                        <button
                          type="button"
                          className="member-remove-btn"
                          onClick={() => onRemoveMember(member.user_id)}
                          title="Remove member"
                        >
                          <Trash2 size={14} />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="modal-footer">
          <button type="button" className="btn btn-primary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
