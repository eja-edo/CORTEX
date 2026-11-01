import type { Me } from '../api/types'

/** What the server says this person may do (`permissions` on /session). The server checks every call anyway; this only decides what to show. */
export const can = (me: Me | null | undefined, perm: string) => !!me?.permissions.includes(perm)
