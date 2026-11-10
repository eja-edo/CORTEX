import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { fail, renderApp, server } from '../test/harness'

const SIGNED_OUT = { 'GET /session': { __status: 401, body: { detail: 'not signed in' } } }

describe('Quên mật khẩu', () => {
  it('shows the link on the sign-in page only when the server can send mail', async () => {
    server({ ...SIGNED_OUT, 'GET /auth/recovery': { enabled: true } })
    renderApp('/login')
    expect(await screen.findByRole('link', { name: 'Quên mật khẩu?' })).toHaveAttribute('href', '/forgot')
  })

  it('keeps the old advice when mail is off', async () => {
    server({ ...SIGNED_OUT, 'GET /auth/recovery': { enabled: false } })
    renderApp('/login')
    expect(await screen.findByText(/Nhờ chủ trung tâm đặt lại/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Quên mật khẩu?' })).toBeNull()
  })

  it('asks for the address and gives the same answer whoever it is', async () => {
    const s = server({ ...SIGNED_OUT, 'GET /auth/recovery': { enabled: true }, 'POST /auth/forgot': { status: 'ok' } })
    renderApp('/forgot')
    await userEvent.type(await screen.findByLabelText('Email đăng nhập'), 'ai-do@nowhere.vn')
    await userEvent.click(screen.getByRole('button', { name: 'Gửi liên kết' }))
    expect(await screen.findByText(/Nếu email này có tài khoản/)).toBeInTheDocument()
    expect(s.posted('/auth/forgot')[0].body).toEqual({ email: 'ai-do@nowhere.vn' })
  })

  it('says plainly that mail is off instead of offering a form that cannot work', async () => {
    server({ ...SIGNED_OUT, 'GET /auth/recovery': { enabled: false } })
    renderApp('/forgot')
    expect(await screen.findByText(/Chưa bật gửi thư/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Email đăng nhập')).toBeNull()
  })

  it('shows the limit in words', async () => {
    server({ ...SIGNED_OUT, 'GET /auth/recovery': { enabled: true }, 'POST /auth/forgot': fail(429, { code: 'RESET_LIMITED', message: 'x' }) })
    renderApp('/forgot')
    await userEvent.type(await screen.findByLabelText('Email đăng nhập'), 'a@b.vn')
    await userEvent.click(screen.getByRole('button', { name: 'Gửi liên kết' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('quá nhiều lần')
  })
})

describe('Đặt mật khẩu mới từ liên kết', () => {
  it('reads the token from the fragment, sends it with the new password, and then offers sign-in', async () => {
    const s = server({ ...SIGNED_OUT, 'POST /auth/reset': { status: 'ok' } })
    renderApp('/reset#token=abc123abc123abc123abc123abc123')
    await userEvent.type(await screen.findByLabelText(/^Mật khẩu mới/), 'Mat-khau-moi-7391')
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu mới'), 'Mat-khau-moi-7391')
    await userEvent.click(screen.getByRole('button', { name: 'Đặt mật khẩu' }))
    expect(await screen.findByText(/Đã đặt mật khẩu mới/)).toBeInTheDocument()
    expect(s.posted('/auth/reset')[0].body).toEqual({ token: 'abc123abc123abc123abc123abc123', password: 'Mat-khau-moi-7391' })
    expect(screen.getByRole('link', { name: 'Đăng nhập' })).toHaveAttribute('href', '/login')
  })

  it('words an invitation as creating a password, and still sends only the token', async () => {
    const s = server({ ...SIGNED_OUT, 'POST /auth/reset': { status: 'ok' } })
    renderApp('/reset#token=abc123abc123abc123abc123abc123&kind=invite')
    expect(await screen.findByRole('heading', { name: 'Tạo mật khẩu' })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/^Mật khẩu mới/), 'Mat-khau-moi-7391')
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu mới'), 'Mat-khau-moi-7391')
    await userEvent.click(screen.getByRole('button', { name: 'Đặt mật khẩu' }))
    expect(await screen.findByText(/Đã tạo mật khẩu/)).toBeInTheDocument()
    expect(s.posted('/auth/reset')[0].body).toEqual({ token: 'abc123abc123abc123abc123abc123', password: 'Mat-khau-moi-7391' })
  })

  it('does not offer a form without a token', async () => {
    server(SIGNED_OUT)
    renderApp('/reset')
    expect(await screen.findByText(/Liên kết thiếu hoặc không đầy đủ/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^Mật khẩu mới/)).toBeNull()
  })

  it('will not send two passwords that differ', async () => {
    const s = server(SIGNED_OUT)
    renderApp('/reset#token=abc123abc123abc123abc123abc123')
    await userEvent.type(await screen.findByLabelText(/^Mật khẩu mới/), 'Mat-khau-moi-7391')
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu mới'), 'Mat-khau-khac-1111')
    expect(screen.getByRole('alert')).toHaveTextContent('chưa giống nhau')
    expect(screen.getByRole('button', { name: 'Đặt mật khẩu' })).toBeDisabled()
    expect(s.posted('/auth/reset')).toHaveLength(0)
  })

  it('tells an expired or used link apart from a weak password, and offers a new link', async () => {
    server({ ...SIGNED_OUT, 'POST /auth/reset': fail(400, { code: 'BAD_RESET_TOKEN', message: 'x' }) })
    renderApp('/reset#token=abc123abc123abc123abc123abc123')
    await userEvent.type(await screen.findByLabelText(/^Mật khẩu mới/), 'Mat-khau-moi-7391')
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu mới'), 'Mat-khau-moi-7391')
    await userEvent.click(screen.getByRole('button', { name: 'Đặt mật khẩu' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('hết hạn')
    expect(screen.getByRole('link', { name: 'Xin liên kết mới' })).toHaveAttribute('href', '/forgot')
  })
})
