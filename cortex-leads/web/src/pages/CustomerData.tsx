import { Download, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { explain, get } from '../api/client'
import { useEraseCustomer } from '../api/hooks'
import { Button, Label, Notice } from '../components/ui'

/** Owner only (the server checks `settings.manage`): take a copy of what is kept about this customer, or erase it. Erasing asks first,
 *  says what it does, and afterwards says what it could not reach. */
export function CustomerData({ conversationId, onErased }: { conversationId: string; onErased?: () => void }) {
  const erase = useEraseCustomer()
  const [ask, setAsk] = useState(false)
  const [err, setErr] = useState<unknown>(null)
  const download = async () => {
    setErr(null)
    try {
      const data = await get<unknown>(`/customers/${conversationId}/export`)
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
      const a = Object.assign(document.createElement('a'), { href: url, download: `khach-${conversationId.slice(0, 8)}.json` })
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) { setErr(e) }
  }
  return (
    <div className="flex flex-col gap-2.5"><Label>Dữ liệu của khách</Label>
      {erase.isSuccess ? (
        <Notice tone="ok"><span className="flex flex-col gap-1"><b>Đã xoá dữ liệu cá nhân của khách này.</b>
          <span className="text-xs">Chưa xoá được: {erase.data.not_reached.join(' ')}</span></span></Notice>
      ) : ask ? (
        <div className="flex flex-col gap-2 rounded-[10px] border border-bad p-3 text-[13px]">
          <b>Xoá dữ liệu cá nhân của khách này?</b>
          <span className="text-xs text-ink-2">Tên, số điện thoại, mã trên nền tảng và nội dung mọi tin nhắn, nháp, ghi nhớ sẽ bị xoá. Nháp đang chờ và tin chưa gửi bị huỷ. Không hoàn tác được. Nên bấm «Tải bản sao» trước nếu khách yêu cầu.</span>
          <div className="flex gap-2"><Button variant="dangerSolid" busy={erase.isPending} onClick={() => erase.mutate(conversationId, { onSuccess: () => onErased?.() })}>Xoá vĩnh viễn</Button><Button onClick={() => setAsk(false)}>Không</Button></div>
          {erase.isError && <p role="alert" className="text-xs text-bad">{explain(erase.error)}</p>}
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button onClick={download}><Download className="size-3.5" aria-hidden />Tải bản sao</Button>
          <Button variant="danger" onClick={() => setAsk(true)}><Trash2 className="size-3.5" aria-hidden />Xoá dữ liệu khách</Button>
        </div>
      )}
      {err != null && <p role="alert" className="text-xs text-bad">{explain(err)}</p>}
    </div>
  )
}
