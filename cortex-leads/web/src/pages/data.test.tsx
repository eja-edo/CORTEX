import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { CatalogImport, CatalogList } from '../api/types'
import { OWNER, STAFF, fail, renderApp, server } from '../test/harness'

const LIST: CatalogList = {
  categories: ['khoa_hoc', 'lich_hoc_thu'], can_import: true, stats: { active: 3, soon: 1, expired: 1, last_import_at: '2026-10-12T03:00:00Z' },
  items: [
    { code: 'IELTS65', name: 'IELTS 6.5 · 12 tuần', category: 'khoa_hoc', price: 6_500_000, unit: 'khoá', valid_until: '2026-12-31T17:00:00Z', version: 1, state: 'ok' },
    { code: 'TOEIC', name: 'Luyện thi TOEIC', category: 'khoa_hoc', price: 4_200_000, unit: null, valid_until: '2026-11-03T17:00:00Z', version: 3, state: 'soon' },
    { code: 'HT-0912', name: 'Học thử 09/12', category: 'lich_hoc_thu', price: 0, unit: null, valid_until: '2026-01-01T17:00:00Z', version: 1, state: 'expired' }],
}
const CHECKED: CatalogImport = { new: 3, changed: 2, unchanged: 6, to_save: 5, dry_run: true, errors: [{ line: 9, message: 'Dòng 9: giá «6,5 triệu» không phải số. Ghi 6500000 (không dấu chấm, phẩy hay chữ).' }] }
const file = (text: string, name = 'bang-gia.csv') => new File([text], name, { type: 'text/csv' })

describe('Dữ liệu', () => {
  it('lists the active rows with price, expiry colour and version, and the four numbers above them', async () => {
    server({ 'GET /session': OWNER, 'GET /catalog': LIST })
    renderApp('/data')
    expect(await screen.findByRole('heading', { name: 'Dữ liệu' })).toBeInTheDocument()
    const tiles = within(screen.getByLabelText('Tổng quan'))
    expect(tiles.getByText('3')).toBeInTheDocument(); expect(tiles.getByText('Sắp hết hạn trong 14 ngày')).toBeInTheDocument()
    const rows = screen.getAllByRole('row').slice(1)
    expect(rows).toHaveLength(3)
    expect(within(rows[0]).getByText('IELTS65')).toBeInTheDocument()
    expect(within(rows[0]).getByText(/6\.500\.000 đ/)).toBeInTheDocument()
    expect(within(rows[0]).getByText(/\/ khoá/)).toBeInTheDocument()
    expect(within(rows[1]).getByText(/sắp hết/)).toBeInTheDocument()
    expect(within(rows[1]).getByText('v3')).toBeInTheDocument()
    expect(within(rows[2]).getByText('Miễn phí')).toBeInTheDocument()
    expect(within(rows[2]).getByText(/quá hạn/)).toBeInTheDocument()
  })

  it('finds a row by code or name and filters by group', async () => {
    server({ 'GET /session': OWNER, 'GET /catalog': LIST })
    renderApp('/data')
    await userEvent.type(await screen.findByLabelText('Tìm theo mã hoặc tên'), 'toeic')
    expect(screen.getAllByRole('row')).toHaveLength(2)
    await userEvent.clear(screen.getByLabelText('Tìm theo mã hoặc tên'))
    await userEvent.selectOptions(screen.getByLabelText('Lọc theo nhóm'), 'lich_hoc_thu')
    expect(screen.getAllByRole('row')).toHaveLength(2)
    await userEvent.type(screen.getByLabelText('Tìm theo mã hoặc tên'), 'zzz')
    expect(screen.getByText('Không có mục nào khớp.')).toBeInTheDocument()
  })

  it('says what to do when there is nothing yet, and shows staff the list without the import button', async () => {
    server({ 'GET /session': STAFF, 'GET /catalog': { ...LIST, items: [], categories: [], can_import: false, stats: { active: 0, soon: 0, expired: 0, last_import_at: null } } })
    renderApp('/data')
    expect(await screen.findByText('Chưa có bảng giá nào')).toBeInTheDocument()
    expect(screen.getByText(/Chỉ chủ doanh nghiệp nhập được/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Nhập từ CSV/ })).toBeNull()
    expect(screen.getByRole('button', { name: /Tải mẫu CSV/ })).toBeInTheDocument()
    expect(screen.queryByLabelText('Tổng quan')).toBeNull() // four tiles of «0» on an empty table said nothing the empty state does not
  })

  it('gives the owner the sidebar item and a clear error when the list cannot be read', async () => {
    server({ 'GET /session': OWNER, 'GET /catalog': fail(500, 'boom') })
    renderApp('/data')
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(within(screen.getByRole('navigation', { name: 'Điều hướng chính' })).getByRole('link', { name: 'Dữ liệu' })).toHaveAttribute('href', '/data')
  })

  it('downloads the sample as a file named by the server', async () => {
    server({ 'GET /session': OWNER, 'GET /catalog': LIST, 'GET /catalog/template': { filename: 'mau-bang-gia.csv', csv: 'code,name\nA,B\n' } })
    let name = '', href = ''
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { name = this.download; href = this.href })
    renderApp('/data')
    await userEvent.click(await screen.findByRole('button', { name: /Tải mẫu CSV/ }))
    await waitFor(() => expect(name).toBe('mau-bang-gia.csv'))
    expect(decodeURIComponent(href)).toContain('code,name')
    click.mockRestore()
  })
})

describe('Nhập từ CSV', () => {
  it('checks the file first (nothing saved), shows counts and the line that is wrong, then saves what was shown', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /catalog': LIST, 'POST /catalog/import': (b: unknown) => ((b as { dry_run: boolean }).dry_run ? CHECKED : { ...CHECKED, dry_run: false }) })
    renderApp('/data')
    await userEvent.click(await screen.findByRole('button', { name: /Nhập từ CSV/ }))
    const dialog = screen.getByRole('dialog', { name: 'Nhập bảng giá từ CSV' })
    await userEvent.upload(within(dialog).getByLabelText('Chọn tệp CSV'), file('code,name,category,price,unit,valid_until\nA,B,x,1,,\n'))
    expect(await within(dialog).findByText('3 mục mới')).toBeInTheDocument()
    expect(within(dialog).getByText('2 đổi → phiên bản mới')).toBeInTheDocument()
    expect(within(dialog).getByText('6 không đổi')).toBeInTheDocument()
    expect(within(dialog).getByText(/Dòng 9: giá «6,5 triệu»/)).toBeInTheDocument()
    expect(s.posted('/catalog/import')).toHaveLength(1)
    expect(s.posted('/catalog/import')[0].body).toMatchObject({ dry_run: true })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Lưu 5 thay đổi' }))
    await waitFor(() => expect(s.posted('/catalog/import')).toHaveLength(2))
    expect(s.posted('/catalog/import')[1]).toMatchObject({ body: { dry_run: false }, csrf: 'csrf-token-1' })
    expect(await screen.findByText(/Đã lưu: 3 mục mới, 2 mục đổi thành phiên bản mới, bỏ qua 1 dòng lỗi/)).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('offers nothing to save when the file changes nothing, and lets the person pick another file', async () => {
    server({ 'GET /session': OWNER, 'GET /catalog': LIST, 'POST /catalog/import': { new: 0, changed: 0, unchanged: 8, errors: [], to_save: 0, dry_run: true } })
    renderApp('/data')
    await userEvent.click(await screen.findByRole('button', { name: /Nhập từ CSV/ }))
    await userEvent.upload(screen.getByLabelText('Chọn tệp CSV'), file('code,name\nA,B\n'))
    expect(await screen.findByRole('button', { name: 'Không có gì để lưu' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Chọn tệp khác' }))
    expect(screen.getByLabelText('Chọn tệp CSV')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Không có gì để lưu' })).toBeNull()
  })

  it('shows the server\'s sentence when the whole file is refused, and refuses a file over 1 MB without sending it', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /catalog': LIST, 'POST /catalog/import': fail(422, { code: 'NO_HEADER', message: 'Dòng đầu phải có các cột code,name,category,price,unit,valid_until (tải tệp mẫu để xem).' }) })
    renderApp('/data')
    await userEvent.click(await screen.findByRole('button', { name: /Nhập từ CSV/ }))
    await userEvent.upload(screen.getByLabelText('Chọn tệp CSV'), file('a,b\n1,2\n'))
    expect(await screen.findByText(/Dòng đầu phải có các cột/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Chọn tệp khác' }))
    await userEvent.upload(screen.getByLabelText('Chọn tệp CSV'), file('x'.repeat(1_000_001), 'to.csv'))
    expect(await screen.findByText(/Tệp lớn quá/)).toBeInTheDocument()
    expect(s.posted('/catalog/import')).toHaveLength(1) // the big one never left the browser
  })
})
