// The one place dates and times are written out in the browser (DESIGN §5.13). Everything is read in the BUSINESS's time
// zone, which the session provides, never the browser's: the 24-hour window, class times and "yesterday" are all the business's.
// Instants arrive as `2026-10-21T03:20:54Z`, days as `2026-10-25`. People read `HH:mm` and `dd/mm` (`dd/mm/yyyy` when the year
// is not the current one). Formatted from parts, not with Intl's own patterns, which differ between browsers.
let zone = 'Asia/Ho_Chi_Minh'
const formats = new Map<string, Intl.DateTimeFormat>()

export function setTimezone(tz: string) {
  zone = tz
}
export const timezone = () => zone

interface Parts { y: number; mo: number; d: number; h: number; mi: number }
function parts(date: Date): Parts {
  let f = formats.get(zone)
  if (!f) {
    f = new Intl.DateTimeFormat('en-GB', { timeZone: zone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    formats.set(zone, f)
  }
  const v = Object.fromEntries(f.formatToParts(date).map((p) => [p.type, p.value]))
  return { y: +v.year, mo: +v.month, d: +v.day, h: +v.hour, mi: +v.minute }
}

const p2 = (n: number) => String(n).padStart(2, '0')
const BARE_DAY = /^(\d{4})-(\d{2})-(\d{2})$/
const dayOf = (p: Parts) => Date.UTC(p.y, p.mo - 1, p.d)

export const clock = (iso: string) => { const p = parts(new Date(iso)); return `${p2(p.h)}:${p2(p.mi)}` }

/** "dd/mm" this year, "dd/mm/yyyy" otherwise. A bare day ("2026-10-25", the customer's promised day) is that calendar day. */
export function dayMonth(iso: string, now = new Date()): string {
  const bare = BARE_DAY.exec(iso)
  const p = bare ? { y: +bare[1], mo: +bare[2], d: +bare[3], h: 0, mi: 0 } : parts(new Date(iso))
  return `${p2(p.d)}/${p2(p.mo)}${p.y === parts(now).y ? '' : `/${p.y}`}`
}

export const dateTime = (iso: string, now = new Date()) => `${clock(iso)} ${dayMonth(iso, now)}`

/** For a tooltip: always complete. */
export function full(iso: string): string {
  const p = parts(new Date(iso))
  return `${p2(p.d)}/${p2(p.mo)}/${p.y} ${p2(p.h)}:${p2(p.mi)}`
}

/** "dd/mm/yyyy" in the business's zone: an expiry date, where the clock time would be noise. */
export const dateOnly = (iso: string) => full(iso).slice(0, 10)

/** What a list row shows: the time today, "Hôm qua", then the date. "Today" is the business's day. */
export function when(iso: string, now = new Date()): string {
  const days = Math.round((dayOf(parts(now)) - dayOf(parts(new Date(iso)))) / 86_400_000)
  return days <= 0 ? clock(iso) : days === 1 ? 'Hôm qua' : dayMonth(iso, now)
}

export function ago(iso: string, now = new Date()): string {
  const mins = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60_000))
  return mins < 90 ? `${mins} phút` : mins < 2880 ? `${Math.round(mins / 60)} giờ` : `${Math.round(mins / 1440)} ngày`
}

export const initials = (name: string) =>
  name.trim().split(/\s+/).slice(-2).map((w) => w[0]?.toUpperCase() ?? '').join('') || '?'

export const num = (n: number | null | undefined) => (n == null ? '–' : n.toLocaleString('vi-VN'))
export const compact = (n: number) => (n >= 1_000_000 ? `${+(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${Math.round(n / 1000)}k` : String(n))

/** The business's calendar day for an instant, as `YYYY-MM-DD` (what the API takes for day filters). */
export function businessDay(now = new Date()): string {
  const p = parts(now)
  return `${p.y}-${p2(p.mo)}-${p2(p.d)}`
}
/** `2026-10-21` -> `21/10/2026`: a picked day always shows its year (a filter must be unambiguous). */
export const dayFull = (ymd: string) => { const b = BARE_DAY.exec(ymd); return b ? `${b[3]}/${b[2]}/${b[1]}` : ymd }
