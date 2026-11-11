/** The platform admin page's own client (WP47): /api/admin, its own cookie (the browser sends it only there) and its own CSRF token.
 *  Nothing here shares state with the console's client: an admin is nobody in the console, and a person of a business is nobody here. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, retryBackoff, retryTransient } from '../api/client'

export interface AdminMe { email: string; name: string; csrf: string; expires_at: string; recovery_left?: number }
export type AiState = 'running' | 'paused' | 'partial' | 'none'
export interface TenantRow {
  id: string; name: string; timezone: string; created_at: string; ai: AiState; sandboxes: number; sandboxes_paused: number
  accounts: number; owners: number; owners_waiting: number; conversations_7d: number; last_login_at: string | null
}
export interface AdminSandbox { id: string; purpose: string; label: string; title: string | null; status: 'active' | 'paused'; send_mode: 'auto' | 'manual' }
export interface AdminAccount {
  id: string; email: string; name: string; role: 'owner' | 'staff' | 'teacher'; status: 'active' | 'disabled'
  invited: boolean; mfa: boolean; sessions: number; last_login_at: string | null; created_at: string
}
export interface TenantDetail extends TenantRow { sandboxes_missing: string[]; sandbox_list: AdminSandbox[]; account_list: AdminAccount[] }
export interface NewTenant { name: string; timezone: string; owner_email: string; owner_name: string }
export interface NewTenantResult { id: string; owner: { email: string; mail_sent: boolean } | null; owner_error?: { code: string; message: string } }

let csrf = ''

export async function adminApi<T>(method: 'GET' | 'POST' | 'PATCH', path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/admin${path}`, {
    method,
    credentials: 'same-origin',
    headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(method !== 'GET' ? { 'X-CSRF-Token': csrf } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? null)
  return data as T
}
const aget = <T>(path: string) => adminApi<T>('GET', path)
const apost = <T>(path: string, body: unknown = {}) => adminApi<T>('POST', path, body)

/** null = not signed in. No refresh token here: when the 30 minutes run out the admin signs in again. */
export function useAdminSession() {
  return useQuery({
    queryKey: ['admin', 'session'],
    retry: retryTransient,  // only a dropped connection or a restarting server; a 401 is an answer
    retryDelay: retryBackoff,
    refetchInterval: 60_000,
    queryFn: async (): Promise<AdminMe | null> => {
      try {
        const me = await aget<AdminMe>('/session')
        csrf = me.csrf
        return me
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
  })
}

export const useAdminLogin = () => useMutation({ mutationFn: (b: { email: string; password: string }) => apost<{ mfa_required: true }>('/session/login', b) })

export function useAdminCode() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (code: string) => apost<AdminMe>('/session/mfa', { code }),
    onSuccess: (me) => { csrf = me.csrf; qc.setQueryData(['admin', 'session'], me) },
  })
}

export function useAdminLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apost<{ ok: true }>('/session/logout'),
    onSettled: () => { csrf = ''; qc.setQueryData(['admin', 'session'], null); qc.removeQueries({ queryKey: ['admin', 'tenants'] }) },
  })
}

export const useTenants = () => useQuery({ queryKey: ['admin', 'tenants'], queryFn: () => aget<{ items: TenantRow[] }>('/tenants') })
export const useTenant = (id: string) => useQuery({ queryKey: ['admin', 'tenants', id], queryFn: () => aget<TenantDetail>(`/tenants/${id}`) })

/** Every change to a business refreshes the list and that business. */
function useChange<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'tenants'] }) })
}
export const useCreateTenant = () => useChange((b: NewTenant) => apost<NewTenantResult>('/tenants', b))
export const useEnsureSandboxes = (id: string) => useChange(() => apost<{ added: string[] }>(`/tenants/${id}/sandboxes/ensure`))
export const usePauseTenant = (id: string) => useChange((b: { paused: boolean; sandbox_id?: string }) => apost<{ changed: number }>(`/tenants/${id}/ai`, b))
export const usePauseAll = () => useChange((b: { paused: boolean; code: string }) => apost<{ tenants: number; sandboxes_changed: number }>('/ai', b))
export const useInviteOwner = (id: string) => useChange((b: { email: string; name: string }) => apost<{ id: string; email: string; mail_sent: boolean }>(`/tenants/${id}/owners`, b))
export const useSendLink = (id: string) => useChange((userId: string) => apost<{ email: string; mail_sent: boolean; kind: 'invite' | 'reset' }>(`/tenants/${id}/users/${userId}/send-link`))
export const useResetMfa = (id: string) => useChange((b: { userId: string; code: string }) => apost<{ sessions_ended: number }>(`/tenants/${id}/users/${b.userId}/mfa/reset`, { code: b.code }))
export type AccountEdit = { userId: string; name?: string; email?: string; code?: string }
export type AccountEdited = { email: string; name: string; email_moved: boolean; sessions_ended: number; mail_sent: boolean | null }
export const useEditAccount = (id: string) => useChange(({ userId, ...b }: AccountEdit) => adminApi<AccountEdited>('PATCH', `/tenants/${id}/users/${userId}`, b))
export const useEndSessions = (id: string) => useChange((userId: string) => apost<{ ended: number }>(`/tenants/${id}/users/${userId}/end-sessions`))

const REFUSALS: Record<string, string> = {
  BAD_CREDENTIALS: 'Email hoặc mật khẩu không đúng.',
  BAD_MFA_CODE: 'Mã không đúng hoặc đã được dùng. Đợi mã mới rồi thử lại.',
  MFA_EXPIRED: 'Đã quá thời gian nhập mã. Hãy đăng nhập lại từ đầu.',
  ADMIN_SIGNED_OUT: 'Phiên quản trị đã hết. Hãy đăng nhập lại.',
  MAIL_OFF: 'Máy chủ chưa cấu hình gửi thư (SMTP và CL_PUBLIC_BASE_URL), nên chưa mời được ai. Cấu hình thư, hoặc dùng `cli create-user --password`.',
  EMAIL_TAKEN: 'Email này đã có tài khoản (ở doanh nghiệp này hoặc doanh nghiệp khác).',
  BAD_EMAIL: 'Email không hợp lệ.',
  BAD_NAME: 'Tên doanh nghiệp cần 2–120 ký tự.',
  BAD_TIMEZONE: 'Múi giờ không hợp lệ (ví dụ: Asia/Ho_Chi_Minh).',
  DISABLED: 'Tài khoản đang bị khoá; chủ doanh nghiệp phải mở lại trước.',
  NOT_FOUND: 'Không tìm thấy.',
  CODE_REQUIRED: 'Đổi email của tài khoản đang dùng cần mã 6 số trong ứng dụng xác thực của bạn.',
  CSRF: 'Phiên đã cũ. Tải lại trang rồi thử lại.',
}
export function adminProblem(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 429) {
      const s = (e.detail as { retry_after_s?: number } | null)?.retry_after_s ?? 0
      return `Quá nhiều lần thử. Hãy đợi ${s > 90 ? `${Math.ceil(s / 60)} phút` : 'ít phút'} rồi thử lại.`
    }
    if (e.code && REFUSALS[e.code]) return REFUSALS[e.code]
    if (e.messages.length) return e.messages.join('; ')
  }
  return 'Không thực hiện được. Thử lại sau.'
}
