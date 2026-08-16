import { useState } from 'react'
import { Sun, Moon, Waves, Trees, Flower2, BookOpen } from 'lucide-react'
import type { GoogleCalendarStatus, ReasonPreference, UserPreferencesResponse } from '../types'
import type { AppTheme } from '../utils/theme'
import { THEME_OPTIONS } from '../utils/theme'

const THEME_ICONS: Record<AppTheme, React.ElementType> = {
  light: Sun,
  dark: Moon,
  ocean: Waves,
  forest: Trees,
  lavender: Flower2,
  sepia: BookOpen,
}

type SettingsPanelProps = {
  googleCalendarStatus: GoogleCalendarStatus | null
  onConnectGoogleCalendar: () => void
  onSyncGoogleCalendarNow: () => void
  onStartGoogleCalendarWatch: () => void
  onRenewGoogleCalendarWatch: () => void
  onDisconnectGoogleCalendar: () => void
  theme: AppTheme
  onThemeChange: (theme: AppTheme) => void
  formatDateTimeVi: (isoDateTime: string | null) => string
  blockEditingEnabled: boolean
  onBlockEditingChange: (enabled: boolean) => void
  // Milestone 6.2 + redesigned 4.5 (A2 follow-up) — see docs/planning-v3.md.
  quietHours: UserPreferencesResponse | null
  onSaveQuietHours: (start: string | null, end: string | null) => Promise<UserPreferencesResponse>
  reasonPreferences: ReasonPreference[]
  onToggleReasonPreference: (reasonKey: string, enabled: boolean) => Promise<void>
}

// "22:00:00" (backend) <-> "22:00" (<input type="time">).
function toTimeInputValue(value: string | null): string {
  return value ? value.slice(0, 5) : ''
}

function fromTimeInputValue(value: string): string | null {
  return value ? `${value}:00` : null
}

export function SettingsPanel({
  googleCalendarStatus,
  onConnectGoogleCalendar,
  onSyncGoogleCalendarNow,
  onStartGoogleCalendarWatch,
  onRenewGoogleCalendarWatch,
  onDisconnectGoogleCalendar,
  theme,
  onThemeChange,
  formatDateTimeVi,
  blockEditingEnabled,
  onBlockEditingChange,
  quietHours,
  onSaveQuietHours,
  reasonPreferences,
  onToggleReasonPreference,
}: SettingsPanelProps) {
  const [quietStart, setQuietStart] = useState(() => toTimeInputValue(quietHours?.quiet_hours_start ?? null))
  const [quietEnd, setQuietEnd] = useState(() => toTimeInputValue(quietHours?.quiet_hours_end ?? null))
  const [savingQuietHours, setSavingQuietHours] = useState(false)

  // Re-sync local inputs whenever fresh data arrives (e.g. on first load —
  // quietHours starts null before the settings view's fetch resolves).
  const quietHoursKey = `${quietHours?.quiet_hours_start ?? ''}|${quietHours?.quiet_hours_end ?? ''}`
  const [syncedKey, setSyncedKey] = useState(quietHoursKey)
  if (quietHoursKey !== syncedKey) {
    setSyncedKey(quietHoursKey)
    setQuietStart(toTimeInputValue(quietHours?.quiet_hours_start ?? null))
    setQuietEnd(toTimeInputValue(quietHours?.quiet_hours_end ?? null))
  }

  const handleSaveQuietHours = async () => {
    setSavingQuietHours(true)
    try {
      await onSaveQuietHours(fromTimeInputValue(quietStart), fromTimeInputValue(quietEnd))
    } finally {
      setSavingQuietHours(false)
    }
  }

  const handleClearQuietHours = async () => {
    setQuietStart('')
    setQuietEnd('')
    setSavingQuietHours(true)
    try {
      await onSaveQuietHours(null, null)
    } finally {
      setSavingQuietHours(false)
    }
  }
  return (
    <section className="settings-workspace">
      <div className="settings-workspace-header">
        <h1 className="page-title">Settings</h1>
      </div>
      
      {/* Appearance Card with Theme Swatches */}
      <div className="settings-card">
        <div className="settings-card-title">Appearance</div>
        <div className="settings-card-subtitle">
          Choose your preferred theme for the interface.
        </div>
        <div className="theme-swatches-grid">
          {THEME_OPTIONS.map((option) => {
            const Icon = THEME_ICONS[option.value]
            const isActive = theme === option.value
            return (
              <button
                key={option.value}
                type="button"
                className={`theme-swatch ${isActive ? 'active' : ''}`}
                onClick={() => onThemeChange(option.value)}
                title={option.label}
              >
                <div 
                  className="theme-swatch-color"
                  style={{ backgroundColor: option.swatch }}
                />
                <Icon size={16} />
                <span className="theme-swatch-label">{option.label}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Notes Card */}
      <div className="settings-card">
        <div className="settings-card-title">Notes</div>
        <div className="settings-card-subtitle">
          Configure how notes are displayed and edited.
        </div>
        <label className="settings-toggle-row">
          <div className="settings-toggle-info">
            <span className="settings-toggle-label">Edit blocks</span>
            <span className="settings-toggle-desc">
              Allow editing note content directly from the block editor (Split / Blocks view).
              When disabled, editing is only available from the raw Markdown side.
            </span>
          </div>
          <input
            type="checkbox"
            className="settings-toggle"
            checked={blockEditingEnabled}
            onChange={(e) => onBlockEditingChange(e.target.checked)}
          />
        </label>
      </div>
      
      {/* Notifications Card — Milestone 6.2 (quiet hours) + redesigned 4.5 (reason toggles) */}
      <div className="settings-card">
        <div className="settings-card-title">Notifications</div>
        <div className="settings-card-subtitle">
          Quiet hours pause non-urgent nudges; the list below lets you turn off individual kinds entirely.
        </div>
        <div className="settings-quiet-hours-row">
          <label className="settings-quiet-hours-field">
            <span>Quiet hours start (UTC)</span>
            <input
              type="time"
              value={quietStart}
              onChange={(e) => setQuietStart(e.target.value)}
            />
          </label>
          <label className="settings-quiet-hours-field">
            <span>Quiet hours end (UTC)</span>
            <input
              type="time"
              value={quietEnd}
              onChange={(e) => setQuietEnd(e.target.value)}
            />
          </label>
          <div className="settings-actions-row">
            <button
              type="button"
              className="btn btn-primary"
              disabled={savingQuietHours || !quietStart || !quietEnd}
              onClick={() => void handleSaveQuietHours()}
            >
              Save
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={savingQuietHours || (!quietHours?.quiet_hours_start && !quietStart)}
              onClick={() => void handleClearQuietHours()}
            >
              Clear
            </button>
          </div>
        </div>

        <div className="settings-reason-list">
          {reasonPreferences.map((reason) => (
            <label key={reason.reason_key} className="settings-toggle-row">
              <div className="settings-toggle-info">
                <span className="settings-toggle-label">{reason.reason_key}</span>
                <span className="settings-toggle-desc">{reason.description}</span>
                {reason.effective_level !== reason.base_level && (
                  // Milestone 6.9 — Feedback Loop auto-downgrade: this
                  // reason quieted down on its own from repeated dismissal,
                  // not from the toggle. Shown so "why is this quieter?"
                  // has an answer without opening attention_log directly.
                  <span className="settings-toggle-note">
                    Tự hạ xuống "{reason.effective_level}" sau {reason.dismiss_count} lần bị bỏ qua
                  </span>
                )}
              </div>
              <input
                type="checkbox"
                className="settings-toggle"
                checked={reason.enabled}
                onChange={(e) => void onToggleReasonPreference(reason.reason_key, e.target.checked)}
              />
            </label>
          ))}
        </div>
      </div>

      {/* Google Calendar Card */}
      <div className="settings-card">
        <div className="settings-card-title">Google Calendar</div>
        <div className="settings-card-subtitle">
          Manage connection and manual sync for your calendar integration.
        </div>
        <div className="settings-actions-row">
          {!googleCalendarStatus?.connected ? (
            <button type="button" className="btn btn-primary" onClick={onConnectGoogleCalendar}>
              Connect Google
            </button>
          ) : googleCalendarStatus?.needs_reauth ? (
            <>
              <button type="button" className="btn btn-primary" onClick={onConnectGoogleCalendar}>
                Reconnect Google
              </button>
              <button type="button" className="btn btn-danger" onClick={onDisconnectGoogleCalendar}>
                Disconnect Google
              </button>
            </>
          ) : (
            <>
              <button type="button" className="btn btn-ghost" onClick={onSyncGoogleCalendarNow}>
                Sync Google
              </button>
              <button type="button" className="btn btn-ghost" onClick={onStartGoogleCalendarWatch}>
                Start Watch
              </button>
              <button type="button" className="btn btn-ghost" onClick={onRenewGoogleCalendarWatch}>
                Renew Watch
              </button>
              <button type="button" className="btn btn-danger" onClick={onDisconnectGoogleCalendar}>
                Disconnect Google
              </button>
            </>
          )}
        </div>
        <div className="settings-meta-list">
          <div>
            Status:{' '}
            {!googleCalendarStatus?.connected
              ? 'Not connected'
              : googleCalendarStatus?.needs_reauth
                ? 'Needs reconnect'
                : 'Connected'}
          </div>
          <div>Last sync: {formatDateTimeVi(googleCalendarStatus?.last_synced_at ?? null)}</div>
          <div>Channel expires: {formatDateTimeVi(googleCalendarStatus?.channel_expiration ?? null)}</div>
          {googleCalendarStatus?.last_sync_error && (
            <div className="settings-meta-error">Last error: {googleCalendarStatus.last_sync_error}</div>
          )}
        </div>
      </div>
    </section>
  )
}
