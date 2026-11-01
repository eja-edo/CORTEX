import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { DateRange, presetRange, rangeLabel, type Range } from './DateRange'
import { businessDay } from './format'

const NOW = new Date('2026-10-21T03:00:00Z') // 10:00 on the 21st in Ho Chi Minh

function Host({ onChange = () => {}, initial = {} }: { onChange?: (r: Range) => void; initial?: Range }) {
  const [v, setV] = useState<Range>(initial)
  return <DateRange value={v} now={NOW} onChange={(r) => { setV(r); onChange(r) }} />
}
const openIt = () => userEvent.click(screen.getByRole('button', { name: /Thời gian/ }))

describe('presetRange', () => {
  it('counts days of the business, not of the browser', () => {
    expect(businessDay(new Date('2026-10-20T20:00:00Z'))).toBe('2026-10-21') // 03:00 next day in Vietnam, still the 20th in Los Angeles
    expect(presetRange('7d', '2026-10-21')).toMatchObject({ from: '2026-10-15', to: '2026-10-21' })
    expect(presetRange('yesterday', '2026-10-01')).toMatchObject({ from: '2026-09-30', to: '2026-09-30' })
    expect(presetRange('month', '2026-10-21')).toMatchObject({ from: '2026-10-01', to: '2026-10-21' })
    expect(presetRange('last_month', '2026-03-10')).toMatchObject({ from: '2026-02-01', to: '2026-02-28' })
    expect(presetRange('last_month', '2026-01-05')).toMatchObject({ from: '2025-12-01', to: '2025-12-31' })
  })
  it('labels a preset by name and a free range by its days', () => {
    expect(rangeLabel({})).toBe('Tất cả thời gian')
    expect(rangeLabel(presetRange('7d', '2026-10-21'))).toBe('7 ngày qua')
    expect(rangeLabel({ from: '2026-10-03', to: '2026-10-09', preset: 'custom' })).toBe('03/10/2026 – 09/10/2026')
  })
})

describe('DateRange', () => {
  it('applies a quick range and shows it on the chip', async () => {
    const onChange = vi.fn()
    render(<Host onChange={onChange} />)
    await openIt()
    await userEvent.click(screen.getByRole('button', { name: '7 ngày qua' }))
    expect(screen.getByText('7 ngày · 15/10 – 21/10')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Áp dụng' }))
    expect(onChange).toHaveBeenCalledWith({ from: '2026-10-15', to: '2026-10-21', preset: '7d' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('button', { name: /7 ngày qua/ })).toBeInTheDocument()
  })

  it('picks a free range with two clicks, the second one backwards starts again, and today is the last day offered', async () => {
    const onChange = vi.fn()
    render(<Host onChange={onChange} />)
    await openIt()
    expect(screen.getByRole('button', { name: '22/10/2026' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '12/10/2026' }))
    await userEvent.click(screen.getByRole('button', { name: '05/10/2026' })) // earlier than the start: new start
    await userEvent.click(screen.getByRole('button', { name: '09/10/2026' }))
    await userEvent.click(screen.getByRole('button', { name: 'Áp dụng' }))
    expect(onChange).toHaveBeenCalledWith({ from: '2026-10-05', to: '2026-10-09', preset: 'custom' })
  })

  it('takes typed days, rejects a bad or future one, and moves the calendar to it', async () => {
    const onChange = vi.fn()
    render(<Host onChange={onChange} />)
    await openIt()
    const from = screen.getByLabelText('Từ ngày'), to = screen.getByLabelText('Đến ngày')
    await userEvent.type(from, '31/02/2026')
    expect(from).toHaveClass('border-bad')
    await userEvent.clear(from)
    await userEvent.type(from, '03/09/2026')
    await userEvent.type(to, '30/10/2026') // tomorrow-ish: after today
    expect(to).toHaveClass('border-bad')
    await userEvent.clear(to)
    await userEvent.type(to, '10/09/2026')
    expect(within(screen.getByRole('dialog')).getByText('Tháng 9, 2026')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Áp dụng' }))
    expect(onChange).toHaveBeenCalledWith({ from: '2026-09-03', to: '2026-09-10', preset: 'custom' })
  })

  it('clears the filter, and closes on Escape without changing anything', async () => {
    const onChange = vi.fn()
    render(<Host onChange={onChange} initial={presetRange('30d', '2026-10-21')} />)
    await openIt()
    await userEvent.click(screen.getByRole('button', { name: 'Hôm nay' }))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(onChange).not.toHaveBeenCalled()
    await openIt()
    await userEvent.click(screen.getByRole('button', { name: 'Xoá lọc' }))
    expect(onChange).toHaveBeenCalledWith({})
    expect(screen.getByRole('button', { name: /Tất cả thời gian/ })).toBeInTheDocument()
  })

  it('disables Apply until a start day exists, and a lone start day means that one day', async () => {
    const onChange = vi.fn()
    render(<Host onChange={onChange} />)
    await openIt()
    expect(screen.getByRole('button', { name: 'Áp dụng' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '14/10/2026' }))
    expect(screen.getByText('Chọn ngày kết thúc')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Áp dụng' }))
    expect(onChange).toHaveBeenCalledWith({ from: '2026-10-14', to: '2026-10-14', preset: 'custom' })
  })
})
