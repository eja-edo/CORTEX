import { beforeEach, describe, expect, it } from 'vitest'
import { ago, clock, compact, dateTime, dayMonth, full, initials, setTimezone, when } from './format'

const NOW = new Date('2026-10-21T08:00:00Z') // 15:00 on 21/10 in Vietnam, 01:00 in Los Angeles (the test process zone)

describe('format (the business zone, never the browser)', () => {
  beforeEach(() => setTimezone('Asia/Ho_Chi_Minh'))

  it('really is running in another zone than the business', () => {
    expect(new Date(NOW).getHours()).toBe(1)
    expect(clock(NOW.toISOString())).toBe('15:00')
  })
  it('reads the same instant in whichever zone the business lives in', () => {
    expect(clock('2026-10-12T03:00:00Z')).toBe('10:00')
    setTimezone('America/New_York')
    expect(clock('2026-10-12T03:00:00Z')).toBe('23:00')
  })
  it('writes a bare promised day as that calendar day, whatever the zone', () => {
    expect(dayMonth('2026-10-25', NOW)).toBe('25/10')
    expect(dayMonth('2026-01-05', NOW)).toBe('05/01')
    setTimezone('Pacific/Kiritimati')
    expect(dayMonth('2026-10-25', NOW)).toBe('25/10')
  })
  it('shows the year only when it is not the current one (the business\'s current year)', () => {
    expect(dayMonth('2027-01-05', NOW)).toBe('05/01/2027')
    expect(dayMonth('2025-12-31', NOW)).toBe('31/12/2025')
    expect(dayMonth('2027-01-05', new Date('2026-12-31T18:00:00Z'))).toBe('05/01') // already 2027 in Vietnam
    expect(dateTime('2027-01-04T20:00:00Z', NOW)).toBe('03:00 05/01/2027')
  })
  it('puts a late-evening UTC instant on the next day in Vietnam', () => {
    expect(dayMonth('2026-10-12T18:30:00Z', NOW)).toBe('13/10')
    expect(full('2026-10-12T18:30:00Z')).toBe('13/10/2026 01:30')
  })
  it('says today as the hour, then "Hôm qua", then the date, by the business\'s midnight', () => {
    expect(when('2026-10-21T01:05:00Z', NOW)).toBe('08:05')
    expect(when('2026-10-20T17:30:00Z', NOW)).toBe('00:30') // 00:30 on the 21st in Vietnam: today, though it is the 20th in UTC
    expect(when('2026-10-20T16:59:00Z', NOW)).toBe('Hôm qua') // 23:59 on the 20th in Vietnam
    expect(when('2026-10-10T08:00:00Z', NOW)).toBe('10/10')
  })
  it('says how long ago in minutes, hours, days', () => {
    expect(ago('2026-10-21T07:48:00Z', NOW)).toBe('12 phút')
    expect(ago('2026-10-21T02:00:00Z', NOW)).toBe('6 giờ')
    expect(ago('2026-10-17T08:00:00Z', NOW)).toBe('4 ngày')
  })
  it('makes initials from the last two words, and compact numbers', () => {
    expect(initials('Nguyễn Minh Anh')).toBe('MA')
    expect(initials('  ')).toBe('?')
    expect(compact(410_000)).toBe('410k')
    expect(compact(20_000_000)).toBe('20M')
  })
})
