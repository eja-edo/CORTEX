import { useMemo } from 'react'
import { Calendar, Clock, FileText, Plus, Zap, ChevronRight } from 'lucide-react'
import type { Workspace } from '../types'
import type { AppNote } from '../hooks/useNotes'
import type { Schedule } from '../types'

interface GlobalHomeProps {
  user: { full_name?: string | null; email?: string | null } | null
  workspaces: Workspace[]
  recentNotes: AppNote[]
  upcomingSchedules: Schedule[]
  onCreateNote: () => void
  onCreateEvent: () => void
  onCreateWorkspace: () => void
  onOpenWorkspace: (workspaceId: string) => void
  onOpenNote: (noteId: string) => void
}

function formatTimeAgo(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffHours < 1) return 'Just now'
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function getGreeting(): string {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

export function GlobalHome({
  user,
  workspaces,
  recentNotes,
  upcomingSchedules,
  onCreateNote,
  onCreateEvent,
  onCreateWorkspace,
  onOpenWorkspace,
  onOpenNote,
}: GlobalHomeProps) {
  const userName = user?.full_name || user?.email?.split('@')[0] || 'User'
  const greeting = getGreeting()

  const recentNotesWithTitles = useMemo(() => {
    return recentNotes
      .slice(0, 10)
      .map(note => ({
        ...note,
        title: note.title || 'Untitled',
      }))
  }, [recentNotes])

  const todaySchedules = useMemo(() => {
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const tomorrow = new Date(today)
    tomorrow.setDate(tomorrow.getDate() + 1)

    return upcomingSchedules.filter(schedule => {
      const scheduleDate = new Date(schedule.start_time)
      return scheduleDate >= today && scheduleDate < tomorrow
    }).slice(0, 5)
  }, [upcomingSchedules])

  const tomorrowSchedules = useMemo(() => {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    tomorrow.setHours(0, 0, 0, 0)
    const dayAfter = new Date(tomorrow)
    dayAfter.setDate(dayAfter.getDate() + 1)

    return upcomingSchedules.filter(schedule => {
      const scheduleDate = new Date(schedule.start_time)
      return scheduleDate >= tomorrow && scheduleDate < dayAfter
    }).slice(0, 5)
  }, [upcomingSchedules])

  return (
    <div className="global-home">
      {/* Welcome Header */}
      <div className="global-home-header">
        <h1 className="global-home-greeting">
          {greeting}, {userName}
        </h1>
        <p className="global-home-subtitle">
          Your automation flows are running smoothly.
        </p>
      </div>

      {/* Dashboard Grid */}
      <div className="global-home-grid">
        {/* Left Column */}
        <div className="global-home-left">
          {/* Upcoming Schedules */}
          <section className="home-card">
            <div className="home-card-header">
              <div className="home-card-header-left">
                <Calendar size={16} className="home-card-header-icon" />
                <h2 className="home-card-header-label">Upcoming</h2>
              </div>
            </div>

            {(todaySchedules.length > 0 || tomorrowSchedules.length > 0) ? (
              <div className="home-schedule-list">
                {todaySchedules.map(schedule => (
                  <div key={schedule.id} className="home-schedule-item">
                    <div className="home-schedule-time-block">
                      <p className="home-schedule-time-value">
                        {new Date(schedule.start_time).toLocaleTimeString('en-US', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </p>
                      <p className="home-schedule-time-label">Today</p>
                    </div>
                    <div className="home-schedule-content">
                      <h4 className="home-schedule-title">{schedule.title}</h4>
                      {schedule.location && (
                        <p className="home-schedule-location">{schedule.location}</p>
                      )}
                    </div>
                  </div>
                ))}
                {tomorrowSchedules.map(schedule => (
                  <div key={schedule.id} className="home-schedule-item home-schedule-item-dim">
                    <div className="home-schedule-time-block">
                      <p className="home-schedule-time-value">
                        {new Date(schedule.start_time).toLocaleTimeString('en-US', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </p>
                      <p className="home-schedule-time-label">Tomorrow</p>
                    </div>
                    <div className="home-schedule-content">
                      <h4 className="home-schedule-title">{schedule.title}</h4>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="home-empty-state">
                <Calendar size={48} className="home-empty-state-icon" />
                <p className="home-empty-state-title">No upcoming events</p>
                <p className="home-empty-state-desc">Events from your calendar will appear here.</p>
              </div>
            )}
          </section>

          {/* Workspaces */}
          <section className="home-card">
            <div className="home-card-header">
              <div className="home-card-header-left">
                <Zap size={16} className="home-card-header-icon" />
                <h2 className="home-card-header-label">Workspaces</h2>
              </div>
            </div>

            {workspaces.length === 0 ? (
              <div className="home-empty-state">
                <Zap size={48} className="home-empty-state-icon" />
                <p className="home-empty-state-title">No workspaces yet</p>
                <p className="home-empty-state-desc">Create your first workspace to get started</p>
                <button
                  className="home-create-workspace-btn"
                  onClick={onCreateWorkspace}
                  style={{ marginTop: '16px', width: 'auto', padding: '8px 24px', borderStyle: 'solid' }}
                >
                  <Plus size={14} />
                  Create Workspace
                </button>
              </div>
            ) : (
              <div className="home-workspace-list">
                {workspaces.map(workspace => (
                  <button
                    key={workspace.id}
                    className="home-workspace-item"
                    onClick={() => onOpenWorkspace(workspace.id)}
                  >
                    <div
                      className="home-workspace-avatar"
                      style={{ background: 'var(--accent)' }}
                    >
                      {workspace.name.charAt(0).toUpperCase()}
                    </div>
                    <div className="home-workspace-info">
                      <div className="home-workspace-name">{workspace.name}</div>
                      <div className="home-workspace-role">
                        {workspace.my_role} &middot; 0 Workflows
                      </div>
                    </div>
                    <ChevronRight size={16} className="home-workspace-chevron" />
                  </button>
                ))}
                <button className="home-create-workspace-btn" onClick={onCreateWorkspace}>
                  <Plus size={14} />
                  Create New Workspace
                </button>
              </div>
            )}
          </section>
        </div>

        {/* Right Column */}
        <div className="global-home-right">
          {/* Quick Actions */}
          <section className="home-card">
            <div className="home-card-header">
              <div className="home-card-header-left">
                <Plus size={16} className="home-card-header-icon" />
                <h2 className="home-card-header-label">Quick Actions</h2>
              </div>
            </div>
            <div className="home-quick-actions">
              <button className="home-quick-action-btn" onClick={onCreateNote}>
                <div className="home-quick-action-icon home-quick-action-icon--primary">
                  <FileText size={22} />
                </div>
                <span>New Note</span>
              </button>
              <button className="home-quick-action-btn" onClick={onCreateEvent}>
                <div className="home-quick-action-icon home-quick-action-icon--secondary">
                  <Calendar size={22} />
                </div>
                <span>New Event</span>
              </button>
            </div>
          </section>

          {/* Recent Activity */}
          <section className="home-card" style={{ flex: 1 }}>
            <div className="home-card-header">
              <div className="home-card-header-left">
                <Clock size={16} className="home-card-header-icon" />
                <h2 className="home-card-header-label">Recent Activity</h2>
              </div>
            </div>
            <div className="home-activity-list">
              {recentNotesWithTitles.length > 0 ? (
                recentNotesWithTitles.map(note => (
                  <button
                    key={note.id}
                    className="home-activity-item"
                    onClick={() => onOpenNote(note.id)}
                  >
                    <div className="home-activity-icon">
                      <FileText size={14} />
                    </div>
                    <div className="home-activity-content">
                      <div className="home-activity-title">{note.title}</div>
                      <div className="home-activity-time">
                        {formatTimeAgo(note.updatedAt)}
                      </div>
                    </div>
                  </button>
                ))
              ) : (
                <div className="home-empty-state">
                  <FileText size={48} className="home-empty-state-icon" />
                  <p className="home-empty-state-title">No recent notes</p>
                  <p className="home-empty-state-desc">Activities from your flows will appear here.</p>
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
