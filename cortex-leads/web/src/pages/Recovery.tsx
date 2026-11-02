import { Brain } from 'lucide-react'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { explain } from '../api/client'
import { useForgot, useRecovery, useResetPassword } from '../api/hooks'
import { Button, Card, Notice } from '../components/ui'

const input = 'rounded-lg border border-line px-3 py-2.5 text-sm font-normal'

function Frame({ title, sub, children }: { title: string; sub: string; children: ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <Card className="w-full max-w-sm p-8">
        <div className="mb-6 flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-lg bg-accent text-white" aria-hidden><Brain className="size-5" /></span>
          <div><h1 className="text-xl font-bold">{title}</h1><p className="text-xs text-ink-2">{sub}</p></div>
        </div>
        {children}
      </Card>
    </div>
  )
}

/** Ask for a link. The answer is the same whether or not the address has an account, and says so. */
export function Forgot() {
  const status = useRecovery()
  const forgot = useForgot()
  const [email, setEmail] = useState('')
  const submit = (e: FormEvent) => { e.preventDefault(); forgot.mutate(email.trim()) }
  const off = status.isSuccess && !status.data.enabled
  return (
    <Frame title="Quên mật khẩu" sub="Chúng tôi gửi liên kết đặt lại qua email">
      {off ? <Notice tone="warn">Chưa bật gửi thư trên máy chủ này. Hãy nhờ chủ trung tâm đặt lại mật khẩu cho bạn (Nhân viên &amp; quyền).</Notice>
        : forgot.isSuccess ? <Notice tone="ok">Nếu email này có tài khoản, một thư kèm liên kết đặt lại mật khẩu đã được gửi. Liên kết dùng được một lần trong 30 phút. Kiểm tra cả thư mục spam.</Notice>
          : <form onSubmit={submit} className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Email đăng nhập
              <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className={input} placeholder="ten@trungtam.vn" /></label>
            {forgot.isError && <p role="alert" className="text-[13px] text-bad">{explain(forgot.error)}</p>}
            <Button variant="primary" type="submit" busy={forgot.isPending} disabled={!email.includes('@')}>Gửi liên kết</Button>
          </form>}
      <p className="mt-4 text-xs"><Link to="/login" className="font-semibold text-accent underline">Quay lại đăng nhập</Link></p>
    </Frame>
  )
}

/** The page the emailed link opens. The token is in the fragment (`#token=…`): it never reaches a server log or a Referer header,
 *  and it is removed from the address bar as soon as it is read. */
export function ResetPassword() {
  const loc = useLocation()
  const nav = useNavigate()
  const [token] = useState(() => new URLSearchParams(loc.hash.replace(/^#/, '')).get('token') ?? '')  // read on the first render, so there is no flash of "no link"
  const reset = useResetPassword()
  const [pw, setPw] = useState('')
  const [again, setAgain] = useState('')
  useEffect(() => { if (loc.hash) nav({ pathname: loc.pathname, search: loc.search, hash: '' }, { replace: true }) }, [loc.hash, loc.pathname, loc.search, nav])
  const mismatch = again.length > 0 && again !== pw
  const submit = (e: FormEvent) => { e.preventDefault(); reset.mutate({ token, password: pw }) }
  return (
    <Frame title="Đặt mật khẩu mới" sub="Chọn mật khẩu cho tài khoản của bạn">
      {reset.isSuccess ? <><Notice tone="ok">Đã đặt mật khẩu mới. Mọi thiết bị đang đăng nhập đã bị đăng xuất.</Notice>
        <p className="mt-4"><Link to="/login" className="text-sm font-semibold text-accent underline">Đăng nhập</Link></p></>
        : !token ? <><Notice tone="bad">Liên kết thiếu hoặc không đầy đủ. Hãy mở đúng liên kết trong thư, hoặc xin liên kết mới.</Notice>
          <p className="mt-4"><Link to="/forgot" className="text-sm font-semibold text-accent underline">Xin liên kết mới</Link></p></>
          : <form onSubmit={submit} className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Mật khẩu mới
              <input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} className={input} />
              <span className="text-xs font-normal text-ink-3">Ít nhất 10 ký tự, có cả chữ và số, không chứa email hay tên của bạn.</span></label>
            <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Nhập lại mật khẩu mới
              <input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} className={input} /></label>
            {mismatch && <p role="alert" className="text-[13px] text-bad">Hai mật khẩu chưa giống nhau.</p>}
            {reset.isError && <p role="alert" className="text-[13px] text-bad">{explain(reset.error)}</p>}
            {reset.isError && <p className="text-xs"><Link to="/forgot" className="font-semibold text-accent underline">Xin liên kết mới</Link></p>}
            <Button variant="primary" type="submit" busy={reset.isPending} disabled={pw.length < 10 || pw !== again}>Đặt mật khẩu</Button>
          </form>}
    </Frame>
  )
}
