"""When a class set to `auto_write` may write a grade without a person looking (WP38). Deliberately narrower than "the model answered": the
suggestion must be one a teacher would have approved unchanged, and the work one the app made (Google refuses a write into the rest).
Anything else stays a suggestion in the queue and the team is told, exactly as in `review` mode."""
from typing import Any


def auto_ok(proposal: dict[str, Any] | None, assignment: Any) -> bool:
    if not proposal or assignment.origin != "app":
        return False
    rows = proposal.get("criteria") or []
    return bool(rows) and all(r.get("verified") for r in rows) and not (proposal.get("problems") or proposal.get("flags") or proposal.get("concerns"))
