import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { setTimezone } from './format'
import { Time } from './Time'

describe('Time', () => {
  beforeEach(() => setTimezone('Asia/Ho_Chi_Minh'))
  it('shows the short form, carries the instant for machines and the full form on hover', () => {
    render(<Time iso="2026-10-12T03:00:00Z" />)
    const t = screen.getByText('10:00')
    expect(t.tagName).toBe('TIME')
    expect(t).toHaveAttribute('datetime', '2026-10-12T03:00:00Z')
    expect(t).toHaveAttribute('title', '12/10/2026 10:00')
  })
  it('can show the date and time together', () => {
    render(<Time iso="2026-10-22T12:00:00Z" as="dateTime" />)
    expect(screen.getByText(/19:00 22\/10/)).toBeInTheDocument()
  })
})
