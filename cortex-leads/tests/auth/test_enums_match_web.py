"""The SPA's `Role` and `Perm` (web/src/api/enums.ts) must say what the server's enums say: a role or permission added on one side only is a
button that shows and a call that is refused, or the reverse."""
import re
from pathlib import Path

from cortex_leads.auth.perms import ROLE_PERMS, Perm
from cortex_leads.auth.roles import Role

TS = (Path(__file__).parents[2] / "web/src/api/enums.ts").read_text()


def _members(name: str) -> dict[str, str]:
    body = re.search(rf"export const {name} = \{{(.*?)\}} as const", TS, re.S)
    assert body, name
    return dict(re.findall(r"(\w+):\s*'([^']+)'", body.group(1)))


def test_roles_are_the_same_on_both_sides() -> None:
    assert _members("Role") == {r.name: r.value for r in Role}


def test_permissions_are_the_same_on_both_sides() -> None:
    assert _members("Perm") == {p.name: p.value for p in Perm}


def test_every_role_has_a_permission_table_and_every_permission_a_holder() -> None:
    assert set(ROLE_PERMS) == set(Role)
    assert set().union(*ROLE_PERMS.values()) == set(Perm)
