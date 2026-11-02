"""What each role may do. One table, so a new endpoint has to name the permission it needs and a test can check the whole API
against it. `owner` holds everything staff hold. A permission is checked on the server for every call; the SPA hides what a
person cannot do only to spare them a refusal."""
STAFF = frozenset({
    "inbox.use",          # read conversations, approve and send drafts, book, record outcomes
    "skills.read", "skills.draft",  # see skills; make and edit their own drafts
    "sandboxes.read",
    "grading.use",        # suggested grades, deciding them, drafting and creating assignments (WP33): a teacher's own work
    "lessons.upload",     # upload a recording to be summarised, and delete the file again (WP35)
    "lessons.read",       # lesson recaps and their transcripts (WP31): the teaching team's own material
    "lessons.release",    # let a finished recap go out to the team's channel and the Classroom course, for a class that waits for a person (WP38)
    "audit.own",          # their own trail
    "account.self",       # change own password, see and end own sessions
})
OWNER = STAFF | frozenset({
    "ai.pause",           # the kill switch
    "skills.manage",      # trial, go live, switch off, edit what is on, delete, restore
    "sandboxes.manage", "tools.manage", "sources.manage",
    "assistant.use",      # the owner's AI and its proposals
    "audit.all", "audit.admin",  # everyone's trail, export, integrity check
    "team.manage",        # accounts of the business
    "settings.manage",    # the business's profile, where pushes go, which channels feed it; erasing a customer's data (WP39-43)
})
ROLE_PERMS: dict[str, frozenset[str]] = {"owner": OWNER, "staff": STAFF}


def can(role: str, perm: str) -> bool:
    return perm in ROLE_PERMS.get(role, frozenset())
