import { useMemo } from 'react'
import { Calendar, Clock, FileText, Plus, Zap, ChevronRight } from 'lucide-react'
import type { Project } from '../types'
import type { AppNote } from '../hooks/useNotes'
import type { Schedule } from '../types'
import { strings } from '../i18n/strings'
import { TodayChecklist } from './TodayChecklist'

interface GlobalHomeProps {
  user: { full_name?: string | null; email?: string | null } | null
  projects: Project[]
  recentNotes: AppNote[]
  upcomingSchedules: Schedule[]
  onCreateProject: () => void
  onOpenProject: (projectId: string) => void
  onOpenNote: (noteId: string) => void
}

function formatTimeAgo(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffHours < 1) return strings.home.timeAgo.justNow
  if (diffHours < 24) return strings.home.timeAgo.hours(diffHours)
  if (diffDays === 1) return 'Hôm qua'
  if (diffDays < 7) return strings.home.timeAgo.days(diffDays)
  return date.toLocaleDateString('vi-VN', { month: 'short', day: 'numeric' })
}

function getGreeting(): string {
  const hour = new Date().getHours()
  if (hour < 12) return 'Chào buổi sáng'
  if (hour < 18) return 'Chào buổi chiều'
  return 'Chào buổi tối'
}

export function GlobalHome({
  user,
  projects,
  recentNotes,
  upcomingSchedules,
  onCreateProject,
  onOpenProject,
  onOpenNote,
}: GlobalHomeProps) {
  /* Falls back to nothing rather than to the email's local part. Greeting a
     person as "duyanhsadg" reads worse than not naming them at all — this is
     the first line they see each day. */
  const userName = user?.full_name?.trim() || null
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
          {userName ? `${greeting}, ${userName}` : greeting}
        </h1>
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
                <h2 className="home-card-header-label">{strings.home.upcoming.title}</h2>
              </div>
            </div>

            {(todaySchedules.length > 0 || tomorrowSchedules.length > 0) ? (
              <div className="home-schedule-list">
                {todaySchedules.map(schedule => (
                  <div key={schedule.id} className="home-schedule-item">
                    <div className="home-schedule-time-block">
                      <p className="home-schedule-time-value">
                         {new Date(schedule.start_time).toLocaleTimeString('vi-VN', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </p>
                      <p className="home-schedule-time-label">{strings.home.today}</p>
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
                         {new Date(schedule.start_time).toLocaleTimeString('vi-VN', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </p>
                      <p className="home-schedule-time-label">{strings.home.tomorrow}</p>
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
                <p className="home-empty-state-title">{strings.home.noUpcomingEvents.title}</p>
                <p className="home-empty-state-desc">{strings.home.noUpcomingEvents.desc}</p>
              </div>
            )}
          </section>

          {/* Dự án — thay chỗ khối workspace cũ. Cùng vị trí, cùng hình
              dạng, nhưng nói về thứ người dùng thật sự làm việc bên trong:
              `projects` là container duy nhất kể từ DESIGN 11.4. */}
          <section className="home-card">
            <div className="home-card-header">
              <div className="home-card-header-left">
                <Zap size={16} className="home-card-header-icon" />
                <h2 className="home-card-header-label">{strings.home.projects.title}</h2>
              </div>
            </div>

            {projects.length === 0 ? (
              <div className="home-empty-state">
                <Zap size={48} className="home-empty-state-icon" />
                <p className="home-empty-state-title">{strings.home.projects.empty.title}</p>
                <p className="home-empty-state-desc">{strings.home.projects.empty.desc}</p>
                <button
                  className="home-create-workspace-btn"
                  onClick={onCreateProject}
                  style={{ marginTop: '16px', width: 'auto', padding: '8px 24px', borderStyle: 'solid' }}
                >
                  <Plus size={14} />
                  {strings.home.projects.createBtn}
                </button>
              </div>
            ) : (
              <div className="home-workspace-list">
                {projects.map(project => (
                  <button
                    key={project.id}
                    className="home-workspace-item"
                    onClick={() => onOpenProject(project.id)}
                  >
                    <div
                      className="home-workspace-avatar"
                      style={{ background: 'var(--accent)' }}
                    >
                      {project.name.charAt(0).toUpperCase()}
                    </div>
                    <div className="home-workspace-info">
                      <div className="home-workspace-name">{project.name}</div>
                      {/* Nguồn gốc trước, rồi số việc: "cái này ở đâu ra?"
                          là câu hay hỏi nhất về một dự án không ai nhớ đã
                          tạo — vì phần lớn dự án sinh ra từ channel, không
                          do ai bấm nút. */}
                      <div className="home-workspace-role">
                        {project.origin === 'derived'
                          ? strings.projects.originDerived
                          : project.origin === 'personal'
                            ? strings.projects.originPersonal
                            : strings.projects.originManual}
                        {' \u00b7 '}
                        {strings.projects.openCount(project.open_task_count)}
                      </div>
                    </div>
                    <ChevronRight size={16} className="home-workspace-chevron" />
                  </button>
                ))}
                <button className="home-create-workspace-btn" onClick={onCreateProject}>
                  <Plus size={14} />
                  {strings.home.projects.createBtn}
                </button>
              </div>
            )}
          </section>
        </div>

        {/* Right Column */}
        <div className="global-home-right">
          {/* Today's tasks — a plain, manageable list + basic actions
              (tick, rename, due date, priority, delete). Replaces the old
              full-width "Hôm nay" section that used to sit above this grid.
              TodayChecklist renders its own header ("Việc hôm nay" + count),
              so this card doesn't add a second one. */}
          <section className="home-card home-today-card">
            <TodayChecklist />
          </section>

          {/* Recent Activity */}
          <section className="home-card" style={{ flex: 1 }}>
            <div className="home-card-header">
              <div className="home-card-header-left">
                <Clock size={16} className="home-card-header-icon" />
                <h2 className="home-card-header-label">{strings.home.recentActivity.title}</h2>
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
                   <p className="home-empty-state-title">{strings.home.recentActivity.noRecentNotes.title}</p>
                   <p className="home-empty-state-desc">{strings.home.recentActivity.noRecentNotes.desc}</p>
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
