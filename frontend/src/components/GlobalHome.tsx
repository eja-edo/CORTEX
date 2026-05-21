import { useMemo } from 'react'
import { Calendar, Clock, FileText, Plus, Zap } from 'lucide-react'
import type { Workspace } from '../types'
import type { AppNote } from '../hooks/useNotes'
import type { Schedule } from '../types'
import { noteTitleFromMd } from '../hooks/useNotes'

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
        title: noteTitleFromMd(note.contentMd),
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
      {/* Header */}
      <div className="global-home-header">
        <h1 className="global-home-greeting">
          {greeting}, {userName}
        </h1>
      </div>

      {/* Main Grid */}
      <div className="global-home-grid">
        {/* Left Column */}
        <div className="global-home-left">
          {/* Upcoming Schedules */}
          <section className="home-section">
            <h2 className="home-section-title">
              <Calendar size={16} />
              Upcoming
            </h2>

            {todaySchedules.length > 0 && (
              <div className="home-section-group">
                <h3 className="home-section-subtitle">Today</h3>
                <div className="home-schedule-list">
                  {todaySchedules.map(schedule => (
                    <div key={schedule.id} className="home-schedule-item">
                      <div className="home-schedule-time">
                        {new Date(schedule.start_time).toLocaleTimeString('en-US', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </div>
                      <div className="home-schedule-content">
                        <div className="home-schedule-title">{schedule.title}</div>
                        {schedule.location && (
                          <div className="home-schedule-location">{schedule.location}</div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {tomorrowSchedules.length > 0 && (
              <div className="home-section-group">
                <h3 className="home-section-subtitle">Tomorrow</h3>
                <div className="home-schedule-list">
                  {tomorrowSchedules.map(schedule => (
                    <div key={schedule.id} className="home-schedule-item">
                      <div className="home-schedule-time">
                        {new Date(schedule.start_time).toLocaleTimeString('en-US', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </div>
                      <div className="home-schedule-content">
                        <div className="home-schedule-title">{schedule.title}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {todaySchedules.length === 0 && tomorrowSchedules.length === 0 && (
              <div className="home-empty-state">
                <Calendar size={24} />
                <p>No upcoming events</p>
              </div>
            )}
          </section>

          {/* Workspaces */}
          <section className="home-section">
            <h2 className="home-section-title">
              <Zap size={16} />
              Workspaces
            </h2>
            {workspaces.length === 0 ? (
              <div className="home-empty-state">
                <Zap size={24} />
                <p>No workspaces yet</p>
                <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                  Create your first workspace to get started
                </p>
                <button
                  className="btn btn-primary"
                  onClick={onCreateWorkspace}
                  style={{ marginTop: '1rem' }}
                >
                  <Plus size={14} style={{ marginRight: '0.5rem' }} />
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
                    <div className="home-workspace-icon">
                      {workspace.name.charAt(0).toUpperCase()}
                    </div>
                    <div className="home-workspace-info">
                      <div className="home-workspace-name">{workspace.name}</div>
                      <div className="home-workspace-role">{workspace.my_role}</div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>

        {/* Right Column */}
        <div className="global-home-right">
          {/* Quick Actions */}
          <section className="home-section">
            <h2 className="home-section-title">
              <Plus size={16} />
              Quick Actions
            </h2>
            <div className="home-quick-actions">
              <button className="home-quick-action-btn" onClick={onCreateNote}>
                <FileText size={18} />
                <span>New Note</span>
              </button>
              <button className="home-quick-action-btn" onClick={onCreateEvent}>
                <Calendar size={18} />
                <span>New Event</span>
              </button>
            </div>
          </section>

          {/* Recent Activity */}
          <section className="home-section">
            <h2 className="home-section-title">
              <Clock size={16} />
              Recent Activity
            </h2>
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
                  <FileText size={24} />
                  <p>No recent notes</p>
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
