"""
Workspace Data Migration Script

Run: python -m scripts.migrate_workspace

For each user:
  1. Create personal workspace (is_personal=True)
  2. Add user to workspace with role 'owner'
  3. Assign all notes and assets of user to that workspace

This script is idempotent and can be safely re-run.
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import SessionLocal


def migrate():
    db = SessionLocal()
    try:
        # Get all users
        users = db.execute(text("SELECT id, email, full_name FROM users")).fetchall()
        total = len(users)
        print(f"Migrating {total} users...")

        for i, user in enumerate(users):
            user_id = user.id
            user_name = user.full_name or user.email

            # 1. Create personal workspace (if not exists)
            result = db.execute(
                text("SELECT id FROM workspaces WHERE owner_id = :uid AND is_personal = true"),
                {"uid": user_id}
            ).first()

            if result:
                workspace_id = result.id
                print(f"  User {i+1}/{total}: Workspace already exists for {user_name}")
            else:
                workspace_id = db.execute(
                    text("""
                        INSERT INTO workspaces (id, owner_id, name, is_personal, created_at, updated_at)
                        VALUES (gen_random_uuid(), :uid, :name, true, NOW(), NOW())
                        RETURNING id
                    """),
                    {"uid": user_id, "name": f"{user_name}'s Workspace"}
                ).scalar()
                print(f"  User {i+1}/{total}: Created workspace for {user_name}")

            # 2. Add owner to workspace_members (if not exists)
            db.execute(
                text("""
                    INSERT INTO workspace_members (id, workspace_id, user_id, role, joined_at)
                    VALUES (gen_random_uuid(), :wid, :uid, 'owner', NOW())
                    ON CONFLICT (workspace_id, user_id) DO NOTHING
                """),
                {"wid": workspace_id, "uid": user_id}
            )

            # 3. Assign notes to workspace
            notes_updated = db.execute(
                text("""
                    UPDATE notes SET workspace_id = :wid
                    WHERE user_id = :uid AND workspace_id IS NULL
                """),
                {"wid": workspace_id, "uid": user_id}
            ).rowcount

            # 4. Assign assets to workspace
            assets_updated = db.execute(
                text("""
                    UPDATE assets SET workspace_id = :wid
                    WHERE user_id = :uid AND workspace_id IS NULL
                """),
                {"wid": workspace_id, "uid": user_id}
            ).rowcount

            # Commit every 100 users
            if (i + 1) % 100 == 0:
                db.commit()
                print(f"  {i+1}/{total} done (committed batch)")

        db.commit()
        print(f"\nMigration complete.")
        print(f"  - {total} users processed")
        print(f"  - All users have personal workspaces")
        print(f"  - All notes and assets assigned to workspaces")

    except Exception as e:
        db.rollback()
        print(f"\nError during migration: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
