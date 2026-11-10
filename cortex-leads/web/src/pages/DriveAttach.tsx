import { FolderOpen, HardDrive, Paperclip, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { explain } from '../api/client'
import { usePickerInfo, usePickerToken, useSession } from '../api/hooks'
import type { MaterialIn } from '../api/types'
import { can } from '../components/can'
import { openDrivePicker } from '../components/drivePicker'
import { Button, Notice } from '../components/ui'
import { field } from './PostingFields'
import { Perm } from '../api/enums'

export const SHARE: Record<MaterialIn['share'], string> = { VIEW: 'Học sinh chỉ xem', EDIT: 'Học sinh cùng sửa một tệp', STUDENT_COPY: 'Mỗi học sinh một bản sao' }

/** What is attached so far: the file's name, what students may do with it, and a way to take it off. The address is not shown or edited: a file comes from the picker or from an upload. */
export function AttachedFiles({ files, setFiles }: { files: MaterialIn[]; setFiles: (f: MaterialIn[]) => void }) {
  if (files.length === 0) return null
  return (
    <ul aria-label="Tệp đã đính kèm" className="flex flex-col gap-1.5">{files.map((f, i) => (
      <li key={`${f.url}-${i}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-app/40 px-3 py-2">
        <Paperclip className="size-4 shrink-0 text-ink-3" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{f.title || 'Tệp trên Drive'}</span>
        <select aria-label={`Quyền của học sinh với tệp ${i + 1}`} value={f.share} onChange={(e) => setFiles(files.map((x, j) => (j === i ? { ...x, share: e.target.value as MaterialIn['share'] } : x)))} className={field}>{Object.entries(SHARE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <button aria-label={`Bỏ tệp ${i + 1}`} className="text-ink-3 hover:text-bad" onClick={() => setFiles(files.filter((_, j) => j !== i))}><Trash2 className="size-4" /></button>
      </li>))}</ul>
  )
}

/** "Chọn từ Google Drive": opens Google's own file dialog on the Drive of a connected account and hands what was chosen to `onPick`.
 *  `classId` starts with that class's account. A teacher (`browse` off) can only upload from their computer into it. */
export function DriveAttach({ classId, onPick }: { classId?: string; onPick: (files: MaterialIn[]) => void }) {
  const info = usePickerInfo(classId)
  const token = usePickerToken()
  const owner = can(useSession().data, Perm.SOURCES_MANAGE)
  const [account, setAccount] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const usable = info.data?.accounts.filter((a) => a.can_pick) ?? []
  const chosen = usable.find((a) => a.id === account) ?? usable.find((a) => a.id === info.data?.default_account_id) ?? usable[0]
  const configured = info.data?.configured ?? false
  const browse = info.data?.browse ?? false
  const open = async () => {
    if (!chosen) return
    setError('')
    setBusy(true)
    try {
      const t = await token.mutateAsync({ accountId: chosen.id, classId })
      await openDrivePicker({ token: t.token, apiKey: t.api_key, appId: t.app_id }, onPick, browse)
    } catch (e) {
      setError(e instanceof Error && e.message === 'PICKER_LOAD_FAILED' ? 'Không mở được hộp chọn tệp của Google. Hãy thử lại.' : explain(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" busy={busy} disabled={!configured || !chosen} onClick={open}><FolderOpen className="size-4" aria-hidden />{busy ? 'Đang mở…' : browse || !info.data ? 'Chọn từ Google Drive' : 'Tải tệp từ máy lên'}</Button>
      </div>
      {info.isError && <p className="text-xs text-ink-3">Chưa lấy được thông tin Google Drive. Hãy tải lại trang.</p>}
      {info.data && !configured && <Notice tone="accent">Chưa bật chọn tệp từ Google Drive trên máy chủ này, nên chưa đính kèm tệp được. Nhờ người quản trị bật (xem README, mục Chọn tệp đính kèm).</Notice>}
      {info.data && configured && !chosen && (
        <Notice tone="warn" action={owner && <Link to="/settings?tab=google" className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px] font-semibold">Kết nối lại Google</Link>}>
          Chưa có tài khoản Google nào cấp quyền Drive nên chưa mở được hộp chọn tệp. {owner ? 'Hãy kết nối lại Google và tick quyền Drive.' : 'Nhờ chủ trung tâm kết nối lại Google với quyền Drive.'}</Notice>)}
      {chosen && configured && (usable.length > 1
        ? <label className="flex flex-wrap items-center gap-2 text-xs text-ink-2"><HardDrive className="size-3.5 text-ink-3" aria-hidden />Chọn từ Drive của
          <select aria-label="Tài khoản Drive" value={chosen.id} onChange={(e) => setAccount(e.target.value)} className={field}>{usable.map((a) => <option key={a.id} value={a.id}>{a.email ?? a.label}</option>)}</select></label>
        : <p className="flex items-center gap-1.5 text-xs text-ink-2"><HardDrive className="size-3.5 text-ink-3" aria-hidden />{browse ? 'Chọn từ Drive của' : 'Tệp được lưu vào Drive của'} {chosen.email ?? chosen.label}</p>)}
      {error && <p role="alert" className="text-xs text-bad">{error}</p>}
    </div>
  )
}
