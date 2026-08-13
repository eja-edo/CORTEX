"""action.extract_html — CSS-selector extraction over a raw HTML string,
typically chained after action.call_api's `body`/`raw_body` output. Pure
parsing, no network — all cases use static HTML fixtures."""

import pytest

from app.actions.base import ActionContext
from app.actions.builtin.extract_html import ExtractHtmlAction

SAMPLE_HTML = """
<html><body>
  <div class="schedule">
    <div class="item"><span class="title">Tiếng Anh 2</span><a href="/room/101">Room 101</a></div>
    <div class="item"><span class="title">Toán rời rạc</span><a href="/room/202">Room 202</a></div>
  </div>
</body></html>
"""


def _context(**overrides) -> ActionContext:
    defaults = dict(
        user_id="test-user",
        workflow_id="test-workflow",
        instance_id="test-instance",
        node_id="test-node",
        trigger_data={},
        previous_outputs={},
    )
    defaults.update(overrides)
    return ActionContext(**defaults)


@pytest.mark.asyncio(loop_scope="session")
async def test_single_match_returns_text_by_default():
    action = ExtractHtmlAction()
    result = await action.execute({"html": SAMPLE_HTML, "selector": ".title"}, _context())

    assert result.success is True
    assert result.output == {"found": True, "value": "Tiếng Anh 2"}


@pytest.mark.asyncio(loop_scope="session")
async def test_multiple_returns_all_matches_as_array():
    action = ExtractHtmlAction()
    result = await action.execute(
        {"html": SAMPLE_HTML, "selector": ".title", "multiple": True}, _context()
    )

    assert result.success is True
    assert result.output == {"count": 2, "values": ["Tiếng Anh 2", "Toán rời rạc"]}


@pytest.mark.asyncio(loop_scope="session")
async def test_attribute_mode_extracts_attribute_value():
    action = ExtractHtmlAction()
    result = await action.execute(
        {"html": SAMPLE_HTML, "selector": ".item a", "extract": "attribute", "attribute": "href"},
        _context(),
    )

    assert result.success is True
    assert result.output == {"found": True, "value": "/room/101"}


@pytest.mark.asyncio(loop_scope="session")
async def test_html_mode_returns_serialized_element():
    action = ExtractHtmlAction()
    result = await action.execute(
        {"html": SAMPLE_HTML, "selector": ".title", "extract": "html"}, _context()
    )

    assert result.success is True
    assert result.output["value"] == '<span class="title">Tiếng Anh 2</span>'


@pytest.mark.asyncio(loop_scope="session")
async def test_no_match_succeeds_with_found_false():
    action = ExtractHtmlAction()
    result = await action.execute({"html": SAMPLE_HTML, "selector": ".nonexistent"}, _context())

    assert result.success is True
    assert result.output == {"found": False, "value": None}


@pytest.mark.asyncio(loop_scope="session")
async def test_missing_html_fails():
    action = ExtractHtmlAction()
    result = await action.execute({"selector": ".title"}, _context())

    assert result.success is False
    assert "html is required" in result.error


@pytest.mark.asyncio(loop_scope="session")
async def test_missing_selector_fails():
    action = ExtractHtmlAction()
    result = await action.execute({"html": SAMPLE_HTML}, _context())

    assert result.success is False
    assert "selector is required" in result.error


@pytest.mark.asyncio(loop_scope="session")
async def test_dom_mode_produces_nested_json_tree():
    action = ExtractHtmlAction()
    html = """
    <div class="user">
        <h1>Nguyen Van A</h1>
        <p>Developer</p>
        <a href="/profile/123">Profile</a>
    </div>
    """
    result = await action.execute({"html": html, "selector": ".user", "extract": "dom"}, _context())

    assert result.success is True
    assert result.output == {
        "found": True,
        "value": {
            "tag": "div",
            "attributes": {"class": ["user"]},
            "children": [
                {"tag": "h1", "text": "Nguyen Van A"},
                {"tag": "p", "text": "Developer"},
                {"tag": "a", "attributes": {"href": "/profile/123"}, "text": "Profile"},
            ],
        },
    }


@pytest.mark.asyncio(loop_scope="session")
async def test_dom_mode_empty_tag_has_no_text_or_children_key():
    action = ExtractHtmlAction()
    result = await action.execute(
        {"html": '<img src="/a.png">', "selector": "img", "extract": "dom"}, _context()
    )

    assert result.success is True
    assert result.output["value"] == {"tag": "img", "attributes": {"src": "/a.png"}}


@pytest.mark.asyncio(loop_scope="session")
async def test_dom_mode_mixed_text_and_tag_children_preserves_order():
    action = ExtractHtmlAction()
    result = await action.execute(
        {"html": "<p>Hello <b>world</b>!</p>", "selector": "p", "extract": "dom"}, _context()
    )

    assert result.success is True
    assert result.output["value"] == {
        "tag": "p",
        "children": [
            {"text": "Hello"},
            {"tag": "b", "text": "world"},
            {"text": "!"},
        ],
    }


@pytest.mark.asyncio(loop_scope="session")
async def test_dom_mode_with_multiple_returns_array_of_trees():
    action = ExtractHtmlAction()
    result = await action.execute(
        {"html": SAMPLE_HTML, "selector": ".item", "extract": "dom", "multiple": True}, _context()
    )

    assert result.success is True
    assert result.output["count"] == 2
    assert result.output["values"][0]["tag"] == "div"
    titles = [v["children"][0]["text"] for v in result.output["values"]]
    assert titles == ["Tiếng Anh 2", "Toán rời rạc"]


@pytest.mark.asyncio(loop_scope="session")
async def test_template_variables_resolve_in_html_field():
    action = ExtractHtmlAction()
    result = await action.execute(
        {"html": "{{trigger.body}}", "selector": ".title"},
        _context(trigger_data={"body": SAMPLE_HTML}),
    )

    assert result.success is True
    assert result.output["value"] == "Tiếng Anh 2"
