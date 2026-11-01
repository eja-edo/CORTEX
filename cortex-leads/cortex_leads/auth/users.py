"""Account operations shared by the console, the command line and the tests, so there is one way to make a person and one set of
rules (the last owner cannot be removed, a changed password ends the other sessions, ...)."""
import re
import unicodedata
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.auth import passwords, sessions
from cortex_leads.core.errors import CortexError
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,200}\.[^@\s]{2,}$")


class AccountError(CortexError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def normalise_email(email: str) -> str:
    e = email.strip().lower()
    if not EMAIL.match(e) or len(e) > 254:
        raise AccountError("BAD_EMAIL", "Email không hợp lệ.")
    return e


def _slug(text_: str) -> str:
    base = unicodedata.normalize("NFKD", text_).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:24] or "nv"


async def _free_ref(s: AsyncSession, tenant_id: UUID, wanted: str) -> str:
    taken = {r for (r,) in (await s.execute(select(m.AppUser.staff_ref).where(m.AppUser.tenant_id == tenant_id))).all()}
    ref, n = wanted, 1
    while ref in taken:
        n += 1
        ref = f"{wanted}-{n}"
    return ref


async def create_user(s: AsyncSession, tenant_id: UUID, *, email: str, name: str, role: str, password: str | None = None,
                      created_by: str, staff_ref: str | None = None) -> tuple[m.AppUser, str]:
    """A new account. Without `password` one is generated and the person must replace it at first sign-in.
    Returns the account and the password that was set (the only time it exists in clear)."""
    email = normalise_email(email)
    name = name.strip()
    if not 2 <= len(name) <= 80 or role not in ("owner", "staff"):
        raise AccountError("BAD_INPUT", "Tên hoặc vai trò không hợp lệ.")
    temp = password is None
    password = password or passwords.temporary_password()
    if errs := passwords.strength_errors(password, email=email, name=name):
        raise AccountError("WEAK_PASSWORD", " ".join(errs))
    # Email is unique across businesses (it is how a sign-in finds its business). This check sees only the caller's own business,
    # so the unique index is the real guard; it is reported the same way.
    ref = staff_ref or await _free_ref(s, tenant_id, _slug(email.split("@")[0]) if role == "staff" else "owner")
    user = m.AppUser(id=uuid7(), tenant_id=tenant_id, email=email, display_name=name, role=role, staff_ref=ref,
                     password_hash=passwords.hash_password(password), must_change_password=temp, created_by=created_by)
    s.add(user)
    try:
        async with s.begin_nested():
            await s.flush()
    except IntegrityError as e:  # unique violation on email or staff_ref
        raise AccountError("EMAIL_TAKEN", "Email này đã có tài khoản.") from e
    return user, password


async def active_owners(s: AsyncSession) -> int:
    return (await s.execute(select(func.count()).select_from(m.AppUser).where(m.AppUser.role == "owner", m.AppUser.status == "active"))).scalar_one()


async def set_password(s: AsyncSession, user: m.AppUser, password: str, *, must_change: bool, now: datetime, keep_session: UUID | None = None) -> int:
    """Sets a new password and ends every other session of that person. Returns how many sessions ended."""
    if errs := passwords.strength_errors(password, email=user.email, name=user.display_name):
        raise AccountError("WEAK_PASSWORD", " ".join(errs))
    user.password_hash = passwords.hash_password(password)
    user.must_change_password, user.password_changed_at = must_change, now
    await s.flush()
    return await sessions.revoke_user(s, user.id, "password_changed", now, keep=keep_session)


async def change_role_or_status(s: AsyncSession, user: m.AppUser, *, role: str | None, status: str | None, now: datetime) -> None:
    """Never leaves a business without an active owner. Disabling a person ends all their sessions at once."""
    new_role, new_status = role or user.role, status or user.status
    if new_role not in ("owner", "staff") or new_status not in ("active", "disabled"):
        raise AccountError("BAD_INPUT", "Vai trò hoặc trạng thái không hợp lệ.")
    was_owner = user.role == "owner" and user.status == "active"
    will_be_owner = new_role == "owner" and new_status == "active"
    if was_owner and not will_be_owner and await active_owners(s) <= 1:
        raise AccountError("LAST_OWNER", "Doanh nghiệp phải còn ít nhất một chủ đang hoạt động.")
    user.role, user.status = new_role, new_status
    await s.flush()
    if new_status == "disabled" or new_role != "owner" and was_owner:
        await sessions.revoke_user(s, user.id, "disabled" if new_status == "disabled" else "role_changed", now)


async def lookup_for_login(email: str) -> m.AppUser | None:
    """Finds the person for a sign-in before any business is known: RLS lets exactly the row with this email through."""
    from cortex_leads.db.session import system_session

    async with system_session() as s:
        await s.execute(text("select set_config('app.login_email', :e, true)"), {"e": email.strip().lower()})
        user = (await s.execute(select(m.AppUser).where(func.lower(m.AppUser.email) == email.strip().lower()))).scalar_one_or_none()
        s.expunge_all()
        return user


def now() -> datetime:
    return datetime.now(UTC)
