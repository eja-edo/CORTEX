import { Sun, Moon, Waves, Trees, Flower2, BookOpen } from 'lucide-react'
import type { GoogleCalendarStatus } from '../types'
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
}: SettingsPanelProps) {
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
          <div>Status: {googleCalendarStatus?.connected ? 'Connected' : 'Not connected'}</div>
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
