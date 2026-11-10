import qrcode from 'qrcode-generator'
import { Check, Copy, Download, KeyRound, ShieldCheck, ShieldOff } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { explain } from '../api/client'
import { useMfaDisable, useMfaEnable, useMfaNewCodes, useMfaSetup, useMfaStatus } from '../api/hooks'
import { SCard, SFoot, SHead, fieldCls } from './settingsUi'
import { Time } from './Time'
import { Badge, Button, ErrorBox, Loading, Modal, Notice } from './ui'

/** The QR code is drawn here in the browser: the secret it holds never leaves this page for anyone else. */
function Qr({ text }: { text: string }) {
  const svg = useMemo(() => {
    const q = qrcode(0, 'M')
    q.addData(text)
    q.make()
    return q.createSvgTag({ cellSize: 4, margin: 2, scalable: true })
  }, [text])
  return <div role="img" aria-label="Mã QR để quét bằng ứng dụng xác thực" className="size-44 shrink-0 rounded-lg border border-line bg-white p-1 [&>svg]:size-full" dangerouslySetInnerHTML={{ __html: svg }} />
}

const codeInput = `${fieldCls} text-center font-mono text-lg tracking-[0.4em]`

/** Ten codes, shown once: copy them, save them as a file, and say so before the window lets go. */
function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const [copied, setCopied] = useState(false)
  const [kept, setKept] = useState(false)
  const text = `Mã dự phòng Cortex (mỗi mã dùng một lần)\n\n${codes.join('\n')}\n`
  const save = () => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
    a.download = 'cortex-ma-du-phong.txt'
    a.click()
    URL.revokeObjectURL(a.href)
  }
  return (
    <div className="flex flex-col gap-4">
      <Notice tone="warn">Cất 10 mã này ở nơi an toàn (in ra, hoặc lưu trong trình quản lý mật khẩu). Mất điện thoại thì dùng một mã để đăng nhập. <b>Mã chỉ hiện lần này.</b></Notice>
      <ol aria-label="Mã dự phòng" className="grid grid-cols-2 gap-2 rounded-lg bg-app p-3 font-mono text-sm">{codes.map((c) => <li key={c} className="text-center">{c}</li>)}</ol>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => { void navigator.clipboard?.writeText(text); setCopied(true) }}>{copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}{copied ? 'Đã chép' : 'Chép'}</Button>
        <Button onClick={save}><Download className="size-4" aria-hidden />Tải tệp .txt</Button>
      </div>
      <label className="flex items-center gap-2.5 text-[13px]"><input type="checkbox" checked={kept} onChange={(e) => setKept(e.target.checked)} className="size-4 accent-[var(--color-accent)]" />Tôi đã cất các mã này</label>
      <div className="flex justify-end"><Button variant="primary" disabled={!kept} onClick={onDone}>Xong</Button></div>
    </div>
  )
}

/** Turning it on: the password, then scan and type the code the app shows (proves the scan worked), then keep the recovery codes. */
function TurnOn({ onClose }: { onClose: () => void }) {
  const setup = useMfaSetup()
  const enable = useMfaEnable()
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const step = enable.data ? 'codes' : setup.data ? 'scan' : 'password'
  const title = step === 'codes' ? 'Lưu mã dự phòng' : step === 'scan' ? 'Quét mã QR' : 'Bật xác thực 2 lớp'
  return (
    <Modal title={title} onClose={onClose} wide>
      <p className="-mt-2 text-xs font-semibold text-ink-3">Bước {step === 'password' ? 1 : step === 'scan' ? 2 : 3} / 3</p>
      {step === 'password' && (
        <form className="flex flex-col gap-3" onSubmit={(e: FormEvent) => { e.preventDefault(); setup.mutate(password) }}>
          <p className="text-[13px] text-ink-2">Mỗi lần đăng nhập, ngoài mật khẩu bạn sẽ nhập thêm mã 6 số từ ứng dụng xác thực trên điện thoại (Google Authenticator, Microsoft Authenticator…). Nhập mật khẩu để bắt đầu.</p>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Mật khẩu hiện tại
            <input autoFocus type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={fieldCls} /></label>
          {setup.isError && <p role="alert" className="text-[13px] text-bad">{explain(setup.error)}</p>}
          <div className="flex justify-end gap-2"><Button type="button" onClick={onClose}>Huỷ</Button><Button variant="primary" type="submit" busy={setup.isPending} disabled={!password}>Tiếp tục</Button></div>
        </form>)}
      {step === 'scan' && setup.data && (
        <form className="flex flex-col gap-4" onSubmit={(e: FormEvent) => { e.preventDefault(); enable.mutate(code) }}>
          <div className="flex flex-wrap items-start gap-4">
            <Qr text={setup.data.uri} />
            <ol className="flex min-w-0 flex-1 basis-56 list-decimal flex-col gap-2 pl-5 text-[13px] text-ink-2">
              <li>Mở ứng dụng xác thực, chọn <b>Thêm tài khoản</b> rồi <b>Quét mã QR</b>.</li>
              <li>Không quét được? Nhập khoá này vào ứng dụng:<code className="mt-1 block rounded bg-app px-2 py-1 font-mono text-xs break-all text-ink">{setup.data.secret.match(/.{1,4}/g)?.join(' ')}</code></li>
              <li>Nhập mã 6 số ứng dụng đang hiện.</li>
            </ol>
          </div>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Mã 6 số
            <input autoFocus inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} className={codeInput} placeholder="123456" /></label>
          {enable.isError && <p role="alert" className="text-[13px] text-bad">{explain(enable.error)}</p>}
          <div className="flex justify-end gap-2"><Button type="button" onClick={onClose}>Huỷ</Button><Button variant="primary" type="submit" busy={enable.isPending} disabled={code.length !== 6}>Bật</Button></div>
        </form>)}
      {step === 'codes' && enable.data && <RecoveryCodes codes={enable.data.recovery_codes} onDone={onClose} />}
    </Modal>
  )
}

/** Turning it off, or making new recovery codes: both need the password and a current code (or one recovery code). */
function Confirm({ what, onClose }: { what: 'off' | 'codes'; onClose: () => void }) {
  const off = useMfaDisable()
  const renew = useMfaNewCodes()
  const run = what === 'off' ? off : renew
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  if (what === 'codes' && renew.data) return <Modal title="Mã dự phòng mới" onClose={onClose} wide><RecoveryCodes codes={renew.data.recovery_codes} onDone={onClose} /></Modal>
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (what === 'off') off.mutate({ password, code: code.trim() }, { onSuccess: onClose })
    else renew.mutate({ password, code: code.trim() })
  }
  return (
    <Modal title={what === 'off' ? 'Tắt xác thực 2 lớp' : 'Tạo lại mã dự phòng'} onClose={onClose}>
      <form className="flex flex-col gap-3" onSubmit={submit}>
        <p className="text-[13px] text-ink-2">{what === 'off' ? 'Sau khi tắt, chỉ cần mật khẩu là đăng nhập được.' : 'Các mã dự phòng cũ sẽ hết hiệu lực.'}</p>
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Mật khẩu hiện tại
          <input autoFocus type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={fieldCls} /></label>
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Mã 6 số trong ứng dụng, hoặc một mã dự phòng
          <input autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} className={`${fieldCls} font-mono`} /></label>
        {run.isError && <p role="alert" className="text-[13px] text-bad">{explain(run.error)}</p>}
        <div className="flex justify-end gap-2"><Button type="button" onClick={onClose}>Huỷ</Button>
          <Button variant={what === 'off' ? 'dangerSolid' : 'primary'} type="submit" busy={run.isPending} disabled={!password || code.trim().length < 6}>{what === 'off' ? 'Tắt' : 'Tạo mã mới'}</Button></div>
      </form>
    </Modal>
  )
}

export function TwoStep() {
  const q = useMfaStatus()
  const [open, setOpen] = useState<'on' | 'off' | 'codes' | null>(null)
  if (q.isPending) return <SCard><Loading /></SCard>
  if (q.isError) return <SCard><ErrorBox onRetry={() => q.refetch()} /></SCard>
  const st = q.data
  return (
    <SCard>
      <SHead title="Xác thực 2 lớp" desc="Ngoài mật khẩu, mỗi lần đăng nhập cần thêm mã 6 số từ điện thoại. Lộ mật khẩu cũng không ai vào được." right={st.enabled ? <Badge tone="ok">Đang bật</Badge> : <Badge>Đang tắt</Badge>} />
      <div className="flex flex-wrap items-center gap-3 px-4 py-4 text-[13px] sm:px-6">
        <span className={`grid size-10 shrink-0 place-items-center rounded-full ${st.enabled ? 'bg-ok-soft text-ok' : 'bg-app text-ink-3'}`}>{st.enabled ? <ShieldCheck className="size-5" aria-hidden /> : <ShieldOff className="size-5" aria-hidden />}</span>
        <p className="min-w-0 flex-1 basis-56 text-ink-2">{st.enabled
          ? <>Bật từ <Time iso={st.enabled_at!} as="dateTime" />. Còn <b className={st.recovery_left <= 3 ? 'text-warn' : 'text-ink'}>{st.recovery_left} mã dự phòng</b>{st.recovery_left <= 3 ? ', nên tạo mã mới.' : '.'}</>
          : 'Chưa bật. Nên bật nếu bạn là chủ hoặc dùng chung máy tính với người khác.'}</p>
      </div>
      <SFoot>{st.enabled ? <>
        <Button onClick={() => setOpen('codes')}><KeyRound className="size-4" aria-hidden />Tạo lại mã dự phòng</Button>
        <Button variant="danger" onClick={() => setOpen('off')}>Tắt</Button>
      </> : <Button variant="primary" onClick={() => setOpen('on')}><ShieldCheck className="size-4" aria-hidden />Bật xác thực 2 lớp</Button>}</SFoot>
      {open === 'on' && <TurnOn onClose={() => setOpen(null)} />}
      {(open === 'off' || open === 'codes') && <Confirm what={open} onClose={() => setOpen(null)} />}
    </SCard>
  )
}
