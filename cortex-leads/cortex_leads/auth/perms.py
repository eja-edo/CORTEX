"""What each role may do. One table, so a new endpoint has to name the permission it needs and a test can check the whole API
against it. `owner` holds everything staff hold. A permission is checked on the server for every call; the SPA hides what a
person cannot do only to spare them a refusal.

`teacher` (WP46) is not a smaller `staff`: it runs the classes it was given and nothing else of the business. `staff` is the other half:
customer care (inbox, drafts, bookings) and no class work at all (2026-11-06). Reaching every class is itself a permission (`classes.all`),
held by the owner only, so a role that does not name it sees none but its own; `console/scope.py` applies that."""
from enum import StrEnum

from cortex_leads.auth.roles import Role


class Perm(StrEnum):
    """Everything a role can be allowed to do. The SPA repeats it in `web/src/api/enums.ts`; a test holds the two equal."""
    ACCOUNT_SELF = "account.self"
    AI_PAUSE = "ai.pause"
    ASSISTANT_USE = "assistant.use"
    AUDIT_ADMIN = "audit.admin"
    AUDIT_ALL = "audit.all"
    AUDIT_OWN = "audit.own"
    CATALOG_MANAGE = "catalog.manage"
    CATALOG_READ = "catalog.read"
    CLASSES_ALL = "classes.all"
    CLASSES_EDIT = "classes.edit"
    GRADING_USE = "grading.use"
    INBOX_USE = "inbox.use"
    LESSONS_READ = "lessons.read"
    LESSONS_RELEASE = "lessons.release"
    LESSONS_UPLOAD = "lessons.upload"
    SANDBOXES_MANAGE = "sandboxes.manage"
    SANDBOXES_READ = "sandboxes.read"
    SETTINGS_MANAGE = "settings.manage"
    SKILLS_DRAFT = "skills.draft"
    SKILLS_MANAGE = "skills.manage"
    SKILLS_READ = "skills.read"
    SOURCES_MANAGE = "sources.manage"
    TEAM_MANAGE = "team.manage"
    TEMPLATES_MANAGE = "templates.manage"
    TOOLS_MANAGE = "tools.manage"


CLASS_WORK = frozenset({  # what a teacher does in a class. Who holds these without `classes.all` holds them for their own classes only
    Perm.GRADING_USE,        # suggested grades, deciding them, drafting and creating assignments (WP33): a teacher's own work
    Perm.LESSONS_UPLOAD,     # upload a recording to be summarised, and delete the file again (WP35)
    Perm.LESSONS_READ,       # lesson recaps and their transcripts (WP31): the teaching team's own material
    Perm.LESSONS_RELEASE,    # let a finished recap go out to the team's channel and the Classroom course, for a class that waits for a person (WP38)
})
STAFF = frozenset({  # customer care and nothing of the classes: the classes are the teachers' and the owner's
    Perm.INBOX_USE,          # read conversations, approve and send drafts, book, record outcomes
    Perm.SKILLS_READ, Perm.SKILLS_DRAFT,  # see skills; make and edit their own drafts
    Perm.SANDBOXES_READ,
    Perm.CATALOG_READ,       # the price list and trial-lesson calendar: what the AI may quote (Dữ liệu)
    Perm.AUDIT_OWN,          # their own trail
    Perm.ACCOUNT_SELF,       # change own password, see and end own sessions
})
TEACHER = CLASS_WORK | frozenset({
    Perm.CLASSES_EDIT,       # a class's name and how much of its work the AI does by itself; what is the owner's alone is refused field by field (console/classes.py)
    Perm.AUDIT_OWN,
    Perm.ACCOUNT_SELF,
})
OWNER = STAFF | CLASS_WORK | frozenset({
    Perm.CLASSES_ALL,        # every class of the business, not only the ones given to this person (WP46)
    Perm.TEMPLATES_MANAGE,   # change the class kinds and assignment templates: they belong to the whole business (WP44)
    Perm.CLASSES_EDIT,
    Perm.AI_PAUSE,           # the kill switch
    Perm.SKILLS_MANAGE,      # trial, go live, switch off, edit what is on, delete, restore
    Perm.SANDBOXES_MANAGE, Perm.TOOLS_MANAGE, Perm.SOURCES_MANAGE,
    Perm.ASSISTANT_USE,      # the owner's AI and its proposals
    Perm.AUDIT_ALL, Perm.AUDIT_ADMIN,  # everyone's trail, export, integrity check
    Perm.TEAM_MANAGE,        # accounts of the business
    Perm.CATALOG_MANAGE,     # import a price list (a changed row becomes a new version)
    Perm.SETTINGS_MANAGE,    # the business's profile, where pushes go, which channels feed it; erasing a customer's data (WP39-43)
})
ROLE_PERMS: dict[Role, frozenset[Perm]] = {Role.OWNER: OWNER, Role.STAFF: STAFF, Role.TEACHER: TEACHER}


def can(role: str, perm: Perm | str) -> bool:
    return perm in ROLE_PERMS.get(role, frozenset())
