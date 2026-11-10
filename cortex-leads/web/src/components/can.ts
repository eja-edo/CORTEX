import type { Me } from '../api/types'
import { Perm, Role } from '../api/enums'

/** What the server says this person may do (`permissions` on /session). The server checks every call anyway; this only decides what to show. */
export const can = (me: Me | null | undefined, perm: Perm) => !!me?.permissions.includes(perm)

/** Where this person starts: a teacher has no inbox, their work is their classes. */
export const homeOf = (me: Me | null | undefined) => (can(me, Perm.INBOX_USE) ? '/inbox' : '/classes')

export const ROLE_LABEL: Record<Role, string> = { [Role.OWNER]: 'Chủ', [Role.STAFF]: 'Nhân viên', [Role.TEACHER]: 'Giáo viên' }

/** The role picker: what each role is, in the order it is offered. */
export const ROLE_OPTIONS: { value: Role; text: string }[] = [
  { value: Role.STAFF, text: 'Nhân viên: trả lời khách, duyệt nháp' },
  { value: Role.TEACHER, text: 'Giáo viên: chỉ quản lý lớp được giao' },
  { value: Role.OWNER, text: 'Chủ: toàn quyền, gồm quản lý tài khoản' },
]
