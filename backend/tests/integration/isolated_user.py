"""
A throwaway user for tests that clear a whole account.

Most integration tests here tag their rows with a title prefix and delete
only those, so sharing the seeded dev account is harmless. Two do not:
`test_today.py` reads *everything* a user owns (that's what the screen
does), and `test_task_flush.py` counts a user's whole pending-task list —
both need an empty account, so both wipe one.

The seeded id they were using belongs to a **real developer account**. Every
`pytest` run was therefore deleting that person's actual tasks. Tests may
not destroy real data to get a clean fixture; they get their own account
instead.
"""

from uuid import UUID

from sqlalchemy import text

# Fixed so rows are recognisable in the dev database, and clearly not a
# person: no login will ever be issued for it.
ISOLATED_TEST_USER_ID = UUID("00000000-0000-4000-a000-0000000000t1".replace("t1", "01"))
ISOLATED_TEST_USER_EMAIL = "pytest-isolated@cortex.invalid"


async def ensure_isolated_user(db) -> UUID:
    """Create the throwaway account if it isn't there yet.

    `.invalid` is reserved by RFC 2606 and can never be a real address, so
    this can't collide with someone's account however the dev database was
    seeded.
    """
    await db.execute(
        text(
            "INSERT INTO users (id, email, full_name, hashed_password, is_active, created_at, updated_at) "
            "VALUES (:id, :email, 'pytest isolated user', 'not-a-real-hash', true, NOW(), NOW()) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": ISOLATED_TEST_USER_ID, "email": ISOLATED_TEST_USER_EMAIL},
    )
    await db.commit()
    return ISOLATED_TEST_USER_ID
