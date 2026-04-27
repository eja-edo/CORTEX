"""
Workspace Data Verification Script

Run: python -m scripts.verify_workspace_data

Verifies that all notes and assets have workspace_id populated
before running the NOT NULL migration.
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import SessionLocal


def verify():
    db = SessionLocal()
    try:
        print("Verifying workspace data integrity...\n")

        # Check notes with NULL workspace_id
        notes_null = db.execute(
            text("SELECT COUNT(*) FROM notes WHERE workspace_id IS NULL")
        ).scalar()

        print(f"Notes with NULL workspace_id: {notes_null}")

        if notes_null > 0:
            print("\n⚠️  WARNING: Some notes do not have workspace_id!")
            print("   Run scripts/migrate_workspace.py before proceeding.\n")

        # Check assets with NULL workspace_id
        assets_null = db.execute(
            text("SELECT COUNT(*) FROM assets WHERE workspace_id IS NULL")
        ).scalar()

        print(f"Assets with NULL workspace_id: {assets_null}")

        if assets_null > 0:
            print("\n⚠️  WARNING: Some assets do not have workspace_id!")
            print("   Run scripts/migrate_workspace.py before proceeding.\n")

        # Check that all users have personal workspaces
        users_without_ws = db.execute(
            text("""
                SELECT COUNT(*) FROM users u
                WHERE NOT EXISTS (
                    SELECT 1 FROM workspaces w
                    WHERE w.owner_id = u.id AND w.is_personal = true
                )
            """)
        ).scalar()

        print(f"\nUsers without personal workspace: {users_without_ws}")

        if users_without_ws > 0:
            print("\n⚠️  WARNING: Some users don't have personal workspaces!")
            print("   Run scripts/migrate_workspace.py before proceeding.\n")

        # Summary
        print("\n" + "=" * 60)
        if notes_null == 0 and assets_null == 0 and users_without_ws == 0:
            print("✅ All checks passed! Safe to run NOT NULL migration.")
            print("\n   Run: alembic upgrade head")
        else:
            print("❌ Data integrity check failed!")
            print("   DO NOT run NOT NULL migration yet.")
            print("   Fix the issues above first.")
        print("=" * 60)

    except Exception as e:
        print(f"\nError during verification: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    verify()
