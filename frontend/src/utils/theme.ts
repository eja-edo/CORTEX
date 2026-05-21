export type AppTheme = 'light' | 'dark' | 'ocean' | 'forest' | 'lavender' | 'sepia'

export const THEME_OPTIONS: { value: AppTheme; label: string; swatch: string }[] = [
  { value: 'light', label: 'Light', swatch: '#ffffff' },
  { value: 'dark', label: 'Dark', swatch: '#191919' },
  { value: 'ocean', label: 'Ocean', swatch: '#1a365d' },
  { value: 'forest', label: 'Forest', swatch: '#1c4532' },
  { value: 'lavender', label: 'Lavender', swatch: '#44337a' },
  { value: 'sepia', label: 'Sepia', swatch: '#f4ecd8' },
]

const THEME_STORAGE_KEY = 'cortex_theme'

export function getStoredTheme(): AppTheme {
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
  
  // Check if stored value is a valid theme
  if (stored) {
    const validThemes: AppTheme[] = ['light', 'dark', 'ocean', 'forest', 'lavender', 'sepia']
    if (validThemes.includes(stored as AppTheme)) {
      console.log('[Theme] Loading stored theme:', stored)
      return stored as AppTheme
    }
  }
  
  // Detect system preference for initial load
  if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
    console.log('[Theme] Using system preference: dark')
    return 'dark'
  }
  console.log('[Theme] Using default: light')
  return 'light'
}

export function setStoredTheme(theme: AppTheme): void {
  console.log('[Theme] Setting theme:', theme)
  window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  applyThemeToDocument(theme)
}

export function applyThemeToDocument(theme: AppTheme): void {
  document.documentElement.setAttribute('data-theme', theme)
}
