"""
Verify that mutating AI tools go through CommandRegistry instead of
instantiating NoteService/ScheduleService directly (Milestone 1.6, Task 1.6.7).
"""

import ast
import sys
from pathlib import Path

MUTATING_TOOLS = [
    "create_note.py",
    "update_note.py",
    "create_schedule.py",
    "update_schedule.py",
]


def check_tool_file(file_path: Path) -> list[str]:
    """Check if tool file has direct service instantiation."""
    issues = []
    tree = ast.parse(file_path.read_text())

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("NoteService", "ScheduleService"):
                issues.append(f"Direct service instantiation: {node.func.id}() at line {node.lineno}")

    return issues


def main() -> int:
    tools_dir = Path(__file__).resolve().parent.parent / "app" / "ai" / "tools"
    all_clear = True

    for tool_file in MUTATING_TOOLS:
        file_path = tools_dir / tool_file
        if not file_path.exists():
            print(f"X {tool_file}: file not found")
            all_clear = False
            continue

        issues = check_tool_file(file_path)
        if issues:
            print(f"X {tool_file}:")
            for issue in issues:
                print(f"    - {issue}")
            all_clear = False
        else:
            print(f"OK {tool_file}: uses CommandRegistry, no direct service instantiation")

    if all_clear:
        print("\nAll mutating tools use CommandRegistry.")
        return 0

    print("\nSome tools still instantiate services directly.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
