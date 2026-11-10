/** Mirror of `cortex_leads/auth/roles.py` (Role) and `cortex_leads/auth/perms.py` (Perm). `tests/auth/test_enums_match_web.py` holds the two equal.
 *  Const objects, not TS `enum`s: the build forbids non-erasable syntax. */

export const Role = { OWNER: 'owner', STAFF: 'staff', TEACHER: 'teacher' } as const
export type Role = (typeof Role)[keyof typeof Role]

export const Perm = {
  ACCOUNT_SELF: 'account.self',
  AI_PAUSE: 'ai.pause',
  ASSISTANT_USE: 'assistant.use',
  AUDIT_ADMIN: 'audit.admin',
  AUDIT_ALL: 'audit.all',
  AUDIT_OWN: 'audit.own',
  CATALOG_MANAGE: 'catalog.manage',
  CATALOG_READ: 'catalog.read',
  CLASSES_ALL: 'classes.all',
  CLASSES_EDIT: 'classes.edit',
  GRADING_USE: 'grading.use',
  INBOX_USE: 'inbox.use',
  LESSONS_READ: 'lessons.read',
  LESSONS_RELEASE: 'lessons.release',
  LESSONS_UPLOAD: 'lessons.upload',
  SANDBOXES_MANAGE: 'sandboxes.manage',
  SANDBOXES_READ: 'sandboxes.read',
  SETTINGS_MANAGE: 'settings.manage',
  SKILLS_DRAFT: 'skills.draft',
  SKILLS_MANAGE: 'skills.manage',
  SKILLS_READ: 'skills.read',
  SOURCES_MANAGE: 'sources.manage',
  TEAM_MANAGE: 'team.manage',
  TEMPLATES_MANAGE: 'templates.manage',
  TOOLS_MANAGE: 'tools.manage',
} as const
export type Perm = (typeof Perm)[keyof typeof Perm]
