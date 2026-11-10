import { ArrowLeft, Brain, ShieldCheck } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { homeOf } from '../components/can'
import { ApiError, explain } from '../api/client'
import { useLogin, useLoginCode, useRecovery, useSession } from '../api/hooks'
import { Button, Card } from '../components/ui'

const input = 'rounded-lg border border-line px-3 py-2.5 text-sm font-normal'

/** A refusal in words that help without helping a guesser: the same line whether the email exists or not. */
export function loginProblem(e: unknown): string {
  if (e instanceof ApiError && e.status === 429) {
    const s = (e.detail as { retry_after_s?: number } | null)?.retry_after_s ?? 0
    return `Quá nhiều lần thử. Hãy đợi ${s > 90 ? `${Math.ceil(s / 60)} phút` : 'ít phút'} rồi thử lại.`
  }
  if (e instanceof ApiError && e.status === 401) return 'Email hoặc mật khẩu không đúng.'
  return explain(e)
}

/** The second step, for someone who turned two-step sign-in on: the code the app shows now, or one recovery code. */
function CodeStep({ onBack }: { onBack: () => void }) {
  const send = useLoginCode()
  const [code, setCode] = useState('')
  const [spare, setSpare] = useState(false)
  const expired = send.error instanceof ApiError && (send.error.detail as { code?: string } | null)?.code === 'MFA_EXPIRED'
  const ready = spare ? code.replace(/[-\s]/g, '').length === 10 : /^\d{6}$/.test(code)
  const submit = (e: FormEvent) => { e.preventDefault(); send.mutate(code.trim()) }
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <div className="flex items-start gap-2.5 rounded-lg bg-accent-soft px-3.5 py-3 text-[13px] text-ink-2">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
        <span>{spare ? 'Nhập một trong các mã dự phòng bạn đã cất. Mỗi mã chỉ dùng được một lần.' : 'Mở ứng dụng xác thực trên điện thoại và nhập mã 6 số đang hiện.'}</span>
      </div>
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold">{spare ? 'Mã dự phòng' : 'Mã xác thực'}
        <input autoFocus key={spare ? 'spare' : 'app'} value={code} onChange={(e) => setCode(spare ? e.target.value : e.target.value.replace(/\D/g, '').slice(0, 6))}
          inputMode={spare ? 'text' : 'numeric'} autoComplete="one-time-code" placeholder={spare ? 'abcde-12345' : '123456'}
          className={`${input} ${spare ? 'font-mono' : 'text-center font-mono text-lg tracking-[0.4em]'}`} /></label>
      {send.isError && <p role="alert" className="text-[13px] text-bad">{send.error instanceof ApiError && send.error.status === 429 ? loginProblem(send.error) : explain(send.error)}</p>}
      {expired ? <Button variant="primary" type="button" onClick={onBack}>Đăng nhập lại</Button>
        : <Button variant="primary" type="submit" busy={send.isPending} disabled={!ready}>Xác nhận</Button>}
      <div className="flex items-center justify-between text-xs">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-ink-2 hover:text-ink"><ArrowLeft className="size-3.5" aria-hidden />Quay lại</button>
        <button type="button" onClick={() => { setSpare(!spare); setCode(''); send.reset() }} className="font-semibold text-accent hover:underline">
          {spare ? 'Dùng mã trong ứng dụng' : 'Mất điện thoại? Dùng mã dự phòng'}</button>
      </div>
    </form>
  )
}

export function Login() {
  const { data: me } = useSession()
  const login = useLogin()
  const recovery = useRecovery()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [asked, setAsked] = useState(false)  // the password was right and the account wants a code
  if (me) return <Navigate to={homeOf(me)} replace />  // straight to where this person starts, not via the inbox
  const submit = (e: FormEvent) => {
    e.preventDefault()
    login.mutate({ email: email.trim(), password }, { onSuccess: (r) => { if ('mfa_required' in r) { setAsked(true); setPassword('') } } })
  }
  return (
    <div className="flex h-full items-center justify-center p-6">
      <Card className="w-full max-w-sm p-6 sm:p-8">
        <div className="mb-6 flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-lg bg-accent text-white" aria-hidden><Brain className="size-5" /></span>
          <div><h1 className="text-xl font-bold">Cortex</h1><p className="text-xs text-ink-2">{asked ? 'Xác thực 2 lớp' : 'Đăng nhập vào trung tâm của bạn'}</p></div>
        </div>
        {asked ? <CodeStep onBack={() => { setAsked(false); login.reset() }} /> : <form onSubmit={submit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Email
            <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className={input} placeholder="ten@trungtam.vn" /></label>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Mật khẩu
            <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={input} /></label>
          {login.isError && <p role="alert" className="text-[13px] text-bad">{loginProblem(login.error)}</p>}
          <Button variant="primary" type="submit" busy={login.isPending} disabled={!email.includes('@') || password.length < 1}>Đăng nhập</Button>
          {recovery.data?.enabled
            ? <p className="text-xs"><Link to="/forgot" className="font-semibold text-accent underline">Quên mật khẩu?</Link></p>
            : <p className="text-xs text-ink-3">Quên mật khẩu? Nhờ chủ trung tâm đặt lại cho bạn.</p>}
        </form>}
      </Card>
    </div>
  )
}
