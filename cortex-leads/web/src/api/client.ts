/** Thin fetch wrapper for /api/v1. The session is an httpOnly cookie; state-changing calls carry the CSRF token. */
export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`)
    this.status = status
    this.detail = detail
  }
  /** Stable code the server gives for a refusal ({"code": "STALE"}); undefined for anything else. */
  get code(): string | undefined {
    const d = this.detail as { code?: string } | null
    return d && typeof d === 'object' ? d.code : undefined
  }
  /** Lint errors of a form: {"errors": [...]} (422) or pydantic's list. */
  get messages(): string[] {
    const d = this.detail as { errors?: string[]; message?: string } | { loc: string[]; msg: string }[] | null
    if (Array.isArray(d)) return d.map((x) => `${x.loc.slice(1).join('.')}: ${x.msg}`)
    if (d && typeof d === 'object') return d.errors ?? (d.message ? [d.message] : [])
    return []
  }
}

let csrf = ''
export const setCsrf = (token: string) => {
  csrf = token
}

export async function api<T>(method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE', path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method,
    credentials: 'same-origin',
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(method !== 'GET' ? { 'X-CSRF-Token': csrf } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? null)
  return data as T
}

const GIVE_UP = new ApiError(0, { code: 'UPLOAD_INTERRUPTED', message: 'Tải lên bị gián đoạn. Kiểm tra mạng rồi thử lại.' })
const EXPIRED = new ApiError(410, { code: 'UPLOAD_EXPIRED', message: 'Phiên tải lên đã hết hạn. Hãy tải lại từ đầu.' })

/** One request of the resumable protocol, to the session URL Cortex was given. No cookie and no CSRF token go to Google: the URL itself is the permission. */
function sendChunk(url: string, body: Blob | null, range: string, onBytes?: (loaded: number) => void): Promise<{ status: number; range: string | null }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', url)
    xhr.setRequestHeader('Content-Range', range)
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onBytes?.(e.loaded) }
    xhr.onload = () => resolve({ status: xhr.status, range: xhr.getResponseHeader('Range') })
    xhr.onerror = () => reject(new Error('network'))
    xhr.send(body)
  })
}

/** Sends a recording straight to Google Drive in chunks (Google: 308 = got it, send the next; 200/201 = finished). A dropped chunk is asked about
 *  and re-sent a few times; a recording can be hundreds of megabytes, so it is never held in memory whole. */
export async function uploadToDrive(file: File, url: string, chunk: number, onProgress?: (percent: number) => void): Promise<void> {
  const total = file.size
  let sent = 0
  let failures = 0
  while (sent < total) {
    const end = Math.min(sent + chunk, total)
    try {
      const r = await sendChunk(url, file.slice(sent, end), `bytes ${sent}-${end - 1}/${total}`, (n) => onProgress?.(Math.round(((sent + n) / total) * 100)))
      if (r.status === 200 || r.status === 201) { onProgress?.(100); return }
      if (r.status === 308) { sent = end; failures = 0; onProgress?.(Math.round((sent / total) * 100)); continue }
      if (r.status === 404 || r.status === 410) throw EXPIRED
      throw new Error(`status ${r.status}`)
    } catch (e) {
      if (e === EXPIRED || ++failures > 3) throw e === EXPIRED ? e : GIVE_UP
      try {  // ask Google how much it has, then go on from there
        const q = await sendChunk(url, null, `bytes */${total}`)
        if (q.status === 200 || q.status === 201) { onProgress?.(100); return }
        const have = /bytes=0-(\d+)/.exec(q.range ?? '')
        if (q.status === 308 && have) sent = Number(have[1]) + 1  // no readable Range: try this chunk again
      } catch { /* the next loop tries the same chunk again */ }
    }
  }
}

export const get = <T>(path: string) => api<T>('GET', path)
export const put = <T>(path: string, body: unknown) => api<T>('PUT', path, body)
export const post = <T>(path: string, body?: unknown) => api<T>('POST', path, body ?? {})

/** What a refusal code means to a person. Unknown codes fall back to a generic line, never a raw code. */
const REFUSALS: Record<string, string> = {
  STALE: 'Khách vừa nhắn thêm: nháp đã cũ, hãy đọc lại tin mới.',
  NOT_PROPOSED: 'Nháp này đã được xử lý rồi.',
  OUTBOUND_OFF: 'Kênh này chưa bật gửi từ hệ thống: hãy tự gửi.',
  NO_SANDBOX: 'Chưa có sandbox Tổng kết buổi học đang chạy.',
  CONNECTOR_TRUST: 'Kênh này chưa được phép gửi từ hệ thống: hãy tự gửi.',
  WINDOW_CLOSED: 'Cửa sổ nhắn đã đóng: hãy tự liên hệ khách.',
  OFFCHANNEL_DRAFT: 'Nháp này dành cho gọi điện hoặc Zalo, không gửi qua kênh được.',
  OPTED_OUT: 'Khách đã từ chối nhận tin.',
  PAUSED: 'Hệ thống đang tạm dừng.',
  SLOT_FULL: 'Buổi này đã hết chỗ.',
  SLOT_GONE: 'Buổi này không còn nữa.',
  NOT_CONFIRMED: 'Lịch này đã được huỷ rồi.',
  NO_DIGEST_SANDBOX: 'Cần tạo sandbox "Báo cáo cho chủ" trước khi trò chuyện với AI tổng.',
  LLM_UNAVAILABLE: 'AI tổng chưa trả lời được lúc này, thử lại sau.',
  NOT_AVAILABLE: 'Mẫu này chưa mở.',
  BAD_CREDENTIALS: 'Email hoặc mật khẩu không đúng.',
  BAD_CURRENT_PASSWORD: 'Mật khẩu hiện tại không đúng.',
  EMAIL_TAKEN: 'Email này đã có tài khoản.',
  LAST_OWNER: 'Doanh nghiệp phải còn ít nhất một chủ đang hoạt động.',
  SELF_CHANGE: 'Bạn không tự đổi được việc này cho chính mình; nhờ một chủ khác.',
  FORBIDDEN: 'Bạn không có quyền làm việc này.',
  NO_FORM: 'Kỹ năng này không tạo từ form nên không sửa ở đây được.',
  DELETED: 'Kỹ năng này đã bị xoá: hãy khôi phục trước.',
  NOT_DELETED: 'Kỹ năng này chưa bị xoá.',
}
export function explain(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code && REFUSALS[e.code]) return REFUSALS[e.code]
    if (e.messages.length) return e.messages.join('; ')
    if (e.status === 403) return 'Bạn không có quyền làm việc này.'
  }
  return 'Không thực hiện được. Thử lại sau.'
}
