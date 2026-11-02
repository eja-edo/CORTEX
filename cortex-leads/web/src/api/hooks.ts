import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, get, post, put, setCsrf, uploadToDrive } from './client'
import { setTimezone } from '../components/format'
import { keepPreviousData } from '@tanstack/react-query'
import type {
  AssignmentList, GradeDecision, GradeDetail, GradeList, LessonDetail, LessonList, NewAssignment, Member, MySession, McpTool, NewSource, SandboxDetail, SourceDetail, SourceList, ToolInSandbox, ToolList,
  AuditDetail, AuditList, AuditQuery, AuditVerify, ChatReply, ChatTurn, ConvFilter, ConvList, Conversation, FormOptions, Me, Proposal, SandboxList, SkillDetail, SkillList,
  SkillPreview, SkillSpec, ClassItem, ClassAssignments, GoogleCourse, GoogleFolder, GoogleList, GradingMode, RecapMode,
  AiOverview, BusinessSettings, Channels, EraseResult, NewChannelResult, NotifyTargets, Onboarding,
} from './types'

/** null = not signed in (a 401 is an answer here, not an error). */
export function useSession() {
  return useQuery({
    queryKey: ['session'],
    retry: false,
    refetchInterval: 30_000,
    queryFn: async (): Promise<Me | null> => {
      try {
        const me = await get<Me>('/session')
        setCsrf(me.csrf)
        setTimezone(me.timezone)
        return me
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
  })
}

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { email: string; password: string }) => post<Me>('/session/login', b),
    onSuccess: (me) => {
      setCsrf(me.csrf)
      setTimezone(me.timezone)
      qc.setQueryData(['session'], me)
    },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => post('/session/logout'),
    onSuccess: () => {
      qc.clear()
      qc.setQueryData(['session'], null)
    },
  })
}

export function useKillSwitch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (paused: boolean) => post('/kill-switch', { paused }),
    onSuccess: () => qc.invalidateQueries(),
  })
}

export const useConversations = (filter: ConvFilter) =>
  useQuery({ queryKey: ['conversations', filter], queryFn: () => get<ConvList>(`/conversations?filter=${filter}`), refetchInterval: 15_000 })
export const useConversation = (id: string | undefined) =>
  useQuery({ queryKey: ['conversation', id], queryFn: () => get<Conversation>(`/conversations/${id}`), enabled: !!id, refetchInterval: 10_000 })

/** Every inbox action ends the same way: what the server now says replaces what we showed. */
export function useInboxAction<V>(run: (v: V) => Promise<unknown>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['conversations'] })
      qc.invalidateQueries({ queryKey: ['conversation'] })
      qc.invalidateQueries({ queryKey: ['session'] })
    },
  })
}

export const useSkills = () => useQuery({ queryKey: ['skills'], queryFn: () => get<SkillList>('/skills') })
export const useSkill = (id: string | undefined) => useQuery({ queryKey: ['skill', id], queryFn: () => get<SkillDetail>(`/skills/${id}`), enabled: !!id })
export const useFormOptions = () => useQuery({ queryKey: ['skill-options'], queryFn: () => get<FormOptions>('/skills/form-options') })
export const usePreviewSkill = () => useMutation({ mutationFn: (spec: SkillSpec) => post<SkillPreview>('/skills/preview', spec) })
export function useCreateSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (spec: SkillSpec) => post<{ id: string }>('/skills', spec),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['skills'] }),
  })
}
function useSkillChange<V>(run: (v: V) => Promise<unknown>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skills'] })
      qc.invalidateQueries({ queryKey: ['skill'] })
      qc.invalidateQueries({ queryKey: ['audit'] })
    },
  })
}
export const useEditSkill = (id: string) => useSkillChange((spec: SkillSpec) => put(`/skills/${id}`, spec))
export const useRevertSkill = (id: string) => useSkillChange((event_id: string) => post(`/skills/${id}/revert`, { event_id }))

export function useSkillVerb() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, verb }: { id: string; verb: 'trial' | 'live' | 'off' | 'again' | 'delete' | 'restore' }) => post(`/skills/${id}/${verb}`),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['skills'] })
      qc.invalidateQueries({ queryKey: ['skill'] })
    },
  })
}

export const useSandboxes = () => useQuery({ queryKey: ['sandboxes'], queryFn: () => get<SandboxList>('/sandboxes'), refetchInterval: 20_000 })
export function useCreateSandbox() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { template: string; title: string }) => post('/sandboxes', b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sandboxes'] }),
  })
}
export function useSandboxVerb() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, verb }: { id: string; verb: 'pause' | 'resume' }) => post(`/sandboxes/${id}/${verb}`),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['sandboxes'] })
      qc.invalidateQueries({ queryKey: ['session'] })
    },
  })
}

export const useProposals = (enabled: boolean) =>
  useQuery({ queryKey: ['proposals'], queryFn: () => get<{ items: Proposal[] }>('/proposals'), enabled })
export function useProposalVerb() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, verb }: { id: string; verb: 'accept' | 'dismiss' }) => post(`/proposals/${id}/${verb}`),
    onSettled: () => qc.invalidateQueries(),
  })
}
export const useChat = () => useMutation({ mutationFn: (messages: ChatTurn[]) => post<ChatReply>('/assistant/chat', { messages }) })

export const auditQueryString = (q: { [K in keyof AuditQuery]?: AuditQuery[K] | undefined }) =>
  Object.entries(q).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')
/** The page you are leaving stays on screen while the next one loads, so the table never flashes empty. */
export const useAudit = (q: AuditQuery) =>
  useQuery({ queryKey: ['audit', q], queryFn: () => get<AuditList>(`/audit?${auditQueryString(q)}`), placeholderData: keepPreviousData })
export const useAuditEvent = (id: string | null) =>
  useQuery({ queryKey: ['audit-event', id], queryFn: () => get<AuditDetail>(`/audit/${id}`), enabled: !!id })
export const useAuditVerify = () => useMutation({ mutationFn: () => get<AuditVerify>('/audit/verify') })

export const useTools = () => useQuery({ queryKey: ['tools'], queryFn: () => get<ToolList>('/tools') })
export const useSandbox = (id: string | undefined) => useQuery({ queryKey: ['sandbox', id], queryFn: () => get<SandboxDetail>(`/sandboxes/${id}`), enabled: !!id })
export const useToolInSandbox = (sandbox: string | undefined, tool: string | null) =>
  useQuery({ queryKey: ['sandbox-tool', sandbox, tool], queryFn: () => get<ToolInSandbox>(`/sandboxes/${sandbox}/tools/${tool}`), enabled: !!sandbox && !!tool })
export function useSwitchTool(sandbox: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ tool, on }: { tool: string; on: boolean }) => post(`/sandboxes/${sandbox}/tools/${tool}/${on ? 'on' : 'off'}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sandbox'] })
      qc.invalidateQueries({ queryKey: ['sandbox-tool'] })
      qc.invalidateQueries({ queryKey: ['tools'] })
    },
  })
}

export const useSources = () => useQuery({ queryKey: ['sources'], queryFn: () => get<SourceList>('/sources') })
export const useSource = (id: string | null) => useQuery({ queryKey: ['source', id], queryFn: () => get<SourceDetail>(`/sources/${id}`), enabled: !!id })
function useSourceChange<V, R = unknown>(run: (v: V) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sources'] })
      qc.invalidateQueries({ queryKey: ['source'] })
      qc.invalidateQueries({ queryKey: ['tools'] })
    },
  })
}
export const useSourceVerb = () => useSourceChange(({ id, verb }: { id: string; verb: 'lock' | 'unlock' | 'review' }) => post(`/sources/${id}/${verb}`))
export const useMoveSource = () => useSourceChange(({ id, sandbox_id }: { id: string; sandbox_id: string }) => put(`/sources/${id}/sandbox`, { sandbox_id }))
export const useCreateSource = () => useSourceChange((b: NewSource) => post<{ id: string }>('/sources', b))
export const useDescribeMcp = () =>
  useMutation({ mutationFn: (b: { url: string; host: string; auth_header?: string; secret?: string }) => post<{ tools: McpTool[] }>('/sources/mcp/describe', b) })

export const useChangePassword = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { current: string; new: string }) => post<{ other_sessions_ended: number }>('/session/password', b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['session'] }),
  })
}
export const useMySessions = () => useQuery({ queryKey: ['my-sessions'], queryFn: () => get<{ items: MySession[] }>('/session/sessions') })
export function useRevokeSession() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (id: string) => post(`/session/sessions/${id}/revoke`), onSuccess: () => qc.invalidateQueries({ queryKey: ['my-sessions'] }) })
}
export function useLogoutAll() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => post('/session/logout-all'),
    onSuccess: () => {
      qc.clear()
      qc.setQueryData(['session'], null)
    },
  })
}

export const useTeam = () => useQuery({ queryKey: ['team'], queryFn: () => get<{ items: Member[]; min_password: number }>('/team') })
function useTeamChange<V, R>(run: (v: V) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: run, onSuccess: () => qc.invalidateQueries({ queryKey: ['team'] }) })
}
export const useAddMember = () => useTeamChange((b: { email: string; name: string; role: 'owner' | 'staff' }) => post<{ id: string; email: string; temporary_password: string }>('/team', b))
export const useUpdateMember = () => useTeamChange(({ id, ...b }: { id: string; role?: 'owner' | 'staff'; status?: 'active' | 'disabled'; name?: string }) => api<Member>('PATCH', `/team/${id}`, b))
export const useResetMember = () => useTeamChange((id: string) => post<{ temporary_password: string; email: string }>(`/team/${id}/reset-password`))
export const useEndMemberSessions = () => useTeamChange((id: string) => post<{ ended: number }>(`/team/${id}/end-sessions`))

export function useSendMode(sandbox: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (mode: 'auto' | 'manual') => post<{ send_mode: string; changed: boolean }>(`/sandboxes/${sandbox}/send-mode`, { mode }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sandbox'] })
      qc.invalidateQueries({ queryKey: ['sandboxes'] })
      qc.invalidateQueries({ queryKey: ['settings', 'ai'] })
      qc.invalidateQueries({ queryKey: ['session'] })
    },
  })
}

export const useLessons = (classId?: string) => useQuery({ queryKey: ['lessons', classId ?? 'all'], queryFn: () => get<LessonList>(classId ? `/lessons?class_id=${classId}` : '/lessons'), refetchInterval: 15_000, placeholderData: keepPreviousData })
export const useLesson = (id: string | null) => useQuery({ queryKey: ['lesson', id], queryFn: () => get<LessonDetail>(`/lessons/${id}`), enabled: !!id })

/** `scope` narrows the list and its counts to one class or one piece of work. */
export const useGrading = (status: string, scope: { assignmentId?: string; classId?: string } = {}) => useQuery({
  queryKey: ['grading', status, scope.assignmentId ?? '', scope.classId ?? ''],
  queryFn: () => get<GradeList>(`/grading?status=${status}${scope.assignmentId ? `&assignment_id=${scope.assignmentId}` : ''}${scope.classId ? `&class_id=${scope.classId}` : ''}`),
  refetchInterval: 15_000,
})
export const useClassAssignments = (classId: string) => useQuery({ queryKey: ['class-assignments', classId], queryFn: () => get<ClassAssignments>(`/classes/${classId}/assignments`), refetchInterval: 15_000 })
export function useAskGrading() {
  const qc = useQueryClient()
  const done = () => { qc.invalidateQueries({ queryKey: ['grading'] }); qc.invalidateQueries({ queryKey: ['class-assignments'] }); qc.invalidateQueries({ queryKey: ['classes'] }) }
  return {
    one: useMutation({ mutationFn: (id: string) => post<{ queued: number }>(`/grading/${id}/grade`, {}), onSettled: done }),
    all: useMutation({ mutationFn: (assignmentId: string) => post<{ queued: number }>(`/assignments/${assignmentId}/grade`, {}), onSettled: done }),
  }
}
export function useReleaseLesson() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (id: string) => post<{ released: string }>(`/lessons/${id}/release`, {}), onSettled: () => { qc.invalidateQueries({ queryKey: ['lessons'] }); qc.invalidateQueries({ queryKey: ['lesson'] }); qc.invalidateQueries({ queryKey: ['classes'] }) } })
}
export const useGradeItem = (id: string | null) => useQuery({ queryKey: ['grade', id], queryFn: () => get<GradeDetail>(`/grading/${id}`), enabled: !!id })
export function useGradeDecision(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: GradeDecision) => post<{ status: string; total?: number; written?: boolean }>(`/grading/${id}/decision`, b),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['grading'] }); qc.invalidateQueries({ queryKey: ['grade', id] }); qc.invalidateQueries({ queryKey: ['sandboxes'] }); qc.invalidateQueries({ queryKey: ['class-assignments'] }); qc.invalidateQueries({ queryKey: ['classes'] }) },
  })
}
export const useAssignments = (classId?: string) => useQuery({ queryKey: ['assignments', classId ?? 'all'], queryFn: () => get<AssignmentList>(classId ? `/assignments?class_id=${classId}` : '/assignments') })
function useAssignmentChange<V, R = unknown>(run: (v: V) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: run, onSettled: () => { qc.invalidateQueries({ queryKey: ['assignments'] }); qc.invalidateQueries({ queryKey: ['class-assignments'] }) } })
}
export const useCreateAssignment = () => useAssignmentChange((b: NewAssignment) => post('/assignments', b))
export const useAiAssignment = () => useAssignmentChange((b: { class_id: string; topic: string; level: string; minutes: number }) => post('/assignments/ai', b))
export const useAssignmentDecision = () =>
  useAssignmentChange((b: { id: string; action: 'approve' | 'reject'; publish?: boolean; due?: string | null }) => post(`/assignments/${b.id}/decision`, { action: b.action, publish: b.publish ?? false, due: b.due ?? null }))

export function useUploadLesson() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (v: { file: File; language: string; classId?: string; onProgress?: (percent: number) => void }) => {
      const ticket = await post<{ name: string; upload_url: string; chunk_bytes: number }>('/lessons/upload/session',
        { name: v.file.name, size: v.file.size, language: v.language, ...(v.classId ? { class_id: v.classId } : {}) })
      await uploadToDrive(v.file, ticket.upload_url, ticket.chunk_bytes, v.onProgress)  // the bytes go to Google, not through Cortex
      return { name: ticket.name }
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['lessons'] }),
  })
}

export const useClasses = () => useQuery({ queryKey: ['classes'], queryFn: () => get<{ items: ClassItem[] }>('/classes') })
function useClassChange<V, R>(run: (v: V) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: run, onSuccess: () => { qc.invalidateQueries({ queryKey: ['classes'] }); qc.invalidateQueries({ queryKey: ['lessons'] }); qc.invalidateQueries({ queryKey: ['google'] }); qc.invalidateQueries({ queryKey: ['class-assignments'] }); qc.invalidateQueries({ queryKey: ['grading'] }) } })
}
export const useAddClass = () => useClassChange((b: { sandbox_id: string; account_id: string; name: string; folder: string; webhook_url?: string; classroom_account_id?: string; classroom_course_id?: string; classroom_course_name?: string; recap_mode?: RecapMode }) => post('/classes', b))
export const useEditClass = () => useClassChange(({ id, ...b }: { id: string; name?: string; webhook_url?: string | null; active?: boolean; classroom_account_id?: string; classroom_course_id?: string; classroom_course_name?: string; recap_mode?: RecapMode; grading_mode?: GradingMode }) => api<ClassItem>('PATCH', `/classes/${id}`, b))
export const useRelinkClass = () => useClassChange((b: { id: string; account_id: string; folder: string }) => api<ClassItem>('POST', `/classes/${b.id}/relink`, { account_id: b.account_id, folder: b.folder }))
export const useDeleteClass = () => useClassChange((id: string) => api<{ deleted: string }>('DELETE', `/classes/${id}`))
export const useDeleteLesson = () => {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (id: string) => api<{ deleted: string }>('DELETE', `/lessons/${id}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ['lessons'] }); qc.invalidateQueries({ queryKey: ['classes'] }) } })
}
export const useGoogle = () => useQuery({ queryKey: ['google'], queryFn: () => get<GoogleList>('/google/accounts') })
export const useGoogleCourses = (id: string, enabled: boolean) =>
  useQuery({ queryKey: ['google', 'courses', id], enabled, retry: false, queryFn: () => get<{ items: GoogleCourse[] }>(`/google/accounts/${id}/courses`) })
export const useConnectGoogle = () => useMutation({ mutationFn: (b: { label: string; kinds: string[] }) => post<{ url: string }>('/google/accounts/connect', b) })
function useGoogleChange<V, R>(run: (v: V) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: run, onSuccess: () => { qc.invalidateQueries({ queryKey: ['google'] }); qc.invalidateQueries({ queryKey: ['sandbox'] }); qc.invalidateQueries({ queryKey: ['lessons'] }) } })
}
export const useReconnectGoogle = () => useMutation({ mutationFn: (b: { id: string; kinds: string[] }) => post<{ url: string }>(`/google/accounts/${b.id}/reconnect`, { kinds: b.kinds }) })
export const useDeleteGoogle = () => useGoogleChange((id: string) => api<{ deleted: string }>('DELETE', `/google/accounts/${id}`))
export const useRevokeGoogle = () => useGoogleChange((id: string) => post(`/google/accounts/${id}/revoke`))
export const useAddClassroom = () => useGoogleChange((b: { sandbox_id: string; account_id: string; course_id: string; label?: string }) => post('/google/classroom-sources', b))
export const useGoogleFolders = (id: string, enabled: boolean) =>
  useQuery({ queryKey: ['google', 'folders', id], enabled, retry: false, queryFn: () => get<{ items: GoogleFolder[]; full: boolean }>(`/google/accounts/${id}/folders`) })
export const useSwitchSource = () => useGoogleChange((b: { kind: string; id: string; active: boolean }) => post(`/google/sources/${b.kind}/${b.id}/active`, { active: b.active }))

// --- Cài đặt (WP39-43) ---
export const useBusiness = () => useQuery({ queryKey: ['settings', 'business'], queryFn: () => get<BusinessSettings>('/settings/business') })
export function useSaveBusiness() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { name: string; timezone: string; hours: { start: string; end: string }; ai_name: string | null }) => put<BusinessSettings>('/settings/business', b),
    onSuccess: (data) => {
      qc.setQueryData(['settings', 'business'], data)
      qc.invalidateQueries({ queryKey: ['session'] })  // the name in the sidebar and the time zone of every time shown
      qc.invalidateQueries({ queryKey: ['settings', 'ai'] })
    },
  })
}
export const useNotifyTargets = () => useQuery({ queryKey: ['settings', 'notify'], queryFn: () => get<NotifyTargets>('/settings/notify-targets') })
function useNotifyChange<V, R>(run: (v: V) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: run, onSuccess: () => qc.invalidateQueries({ queryKey: ['settings', 'notify'] }) })
}
export const useAddTarget = () => useNotifyChange((b: { kind: 'telegram' | 'mezon'; address: string; label?: string; sandbox_id?: string | null }) => post('/settings/notify-targets', b))
export const useRemoveTarget = () => useNotifyChange((id: string) => api('DELETE', `/settings/notify-targets/${id}`))
export const useTestTarget = () => useMutation({ mutationFn: (id: string) => post<{ ok: boolean }>(`/settings/notify-targets/${id}/test`) })

export const useChannels = () => useQuery({ queryKey: ['settings', 'channels'], queryFn: () => get<Channels>('/settings/channels') })
function useChannelChange<V, R>(run: (v: V) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings', 'channels'] })
      qc.invalidateQueries({ queryKey: ['onboarding'] })
      qc.invalidateQueries({ queryKey: ['sandboxes'] })
    },
  })
}
export const useAddChannel = () => useChannelChange((b: { kind: string; sandbox_id: string }) => post<NewChannelResult>('/settings/channels', b))
export const useRemoveChannel = () => useChannelChange((id: string) => api('DELETE', `/settings/channels/${id}`))
export const useAiOverview = () => useQuery({ queryKey: ['settings', 'ai'], queryFn: () => get<AiOverview>('/settings/ai') })

export const useOnboarding = () => useQuery({ queryKey: ['onboarding'], queryFn: () => get<Onboarding>('/onboarding') })
export const useRecovery = () => useQuery({ queryKey: ['recovery'], queryFn: () => get<{ enabled: boolean }>('/auth/recovery'), retry: false })
export const useForgot = () => useMutation({ mutationFn: (email: string) => post('/auth/forgot', { email }) })
export const useResetPassword = () => useMutation({ mutationFn: (b: { token: string; password: string }) => post('/auth/reset', b) })
export const useEraseCustomer = () => useMutation({ mutationFn: (conversationId: string) => post<EraseResult>(`/customers/${conversationId}/erase`, { confirm: true }), onSuccess: () => undefined })
