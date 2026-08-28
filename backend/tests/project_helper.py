"""Getting a valid `project_id` for tests that build `Task` rows directly.

`tasks.project_id` is NOT NULL (see `docs/DESIGN.md` 3.3): every task
belongs to exactly one project. Tests that construct `Task(...)` by hand —
rather than going through `TaskService.create_task`, which resolves the
project itself (3.5) — have to supply one.

None of those tests care *which* project, only that the row is valid, so
both helpers return the user's personal project and create it on first use.
That mirrors what the bottom rung of the real ladder does, which keeps the
fixtures honest: a hand-built task lands where a service-built one with no
context would.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.models import Project, ProjectJoinSource, ProjectMember, ProjectOrigin


async def personal_project_id(db, user_id) -> UUID:
    """Async sessions. Commits, so the id is usable by other sessions."""
    from app.services.projects import ProjectService

    project = await ProjectService(db).get_or_create_personal(user_id)
    await db.commit()
    return project.id


def personal_project_id_sync(db, user_id) -> UUID:
    """Sync sessions (`sync_session()`), where `ProjectService` can't run.

    Kept deliberately small and duplicated rather than shared through some
    async-to-sync bridge: two short inserts are easier to trust in a test
    helper than a bridge that has to be right under both event loops.
    """
    project = db.execute(
        select(Project).where(
            Project.owner_id == user_id, Project.origin == ProjectOrigin.PERSONAL
        )
    ).scalar_one_or_none()
    if project is not None:
        return project.id

    project = Project(owner_id=user_id, name="Cá nhân", origin=ProjectOrigin.PERSONAL)
    db.add(project)
    db.flush()
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=user_id,
            joined_via=ProjectJoinSource.DERIVED,
        )
    )
    db.commit()
    return project.id
