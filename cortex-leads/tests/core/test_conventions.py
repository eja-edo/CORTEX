"""DESIGN §5.13 as a guard on the source: dates and times are written by `core/timefmt.py` and nowhere else, so a new
screen or a new field cannot grow a format of its own."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "cortex_leads"
ALLOWED = {"core/timefmt.py", "cli.py"}  # cli.py: a timestamp in the operator's own terminal log, not data


def offenders() -> list[str]:
    found = []
    for py in ROOT.rglob("*.py"):
        rel = str(py.relative_to(ROOT))
        if rel in ALLOWED:
            continue
        for node in ast.walk(ast.parse(py.read_text())):
            if isinstance(node, ast.Attribute) and node.attr in ("isoformat", "strftime", "utcnow", "utcfromtimestamp"):
                found.append(f"{rel}:{node.lineno} .{node.attr}")
            if isinstance(node, ast.FormattedValue) and isinstance(node.format_spec, ast.JoinedStr) \
                    and any("%" in str(getattr(v, "value", "")) for v in node.format_spec.values):
                found.append(f"{rel}:{node.lineno} strftime-style f-string")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "now" \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "datetime" \
                    and not node.args and not node.keywords:
                found.append(f"{rel}:{node.lineno} naive .now()")
    return found


def test_no_module_writes_dates_or_times_by_itself():
    assert offenders() == [], "use cortex_leads.core.timefmt (wire / wire_date / vi_* / stamp); see DESIGN §5.13"
