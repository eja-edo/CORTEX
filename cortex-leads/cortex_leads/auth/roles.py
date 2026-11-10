"""The roles of the console. One definition: the SPA's `web/src/api/enums.ts` repeats it and `tests/auth/test_enums_match_web.py` holds the two equal.
A `StrEnum` member *is* its string, so rows, JSON and the CHECK constraints keep the same text."""
from enum import StrEnum


class Role(StrEnum):
    """Who a signed-in person is (`app_user.role`). What each may do is `perms.ROLE_PERMS`."""
    OWNER = "owner"
    STAFF = "staff"
    TEACHER = "teacher"


class ApiRole(StrEnum):
    """What an API key stands for (`api_key.role`): the bridge and the review endpoints, not a person in the console."""
    OWNER = "owner"
    STAFF = "staff"
    SUPERVISOR = "supervisor"
