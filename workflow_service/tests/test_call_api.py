"""action.call_api — parses the response according to its Content-Type
(JSON/XML/HTML/text). Hits real httpbin.org endpoints (same external-service
pattern tests/test_execute_node.py already uses for action.call_api) since
each content-type path depends on a real server actually setting that header.
"""

import pytest

from app.actions.base import ActionContext
from app.actions.builtin.call_api import CallApiAction, _xml_element_to_dict
import xml.etree.ElementTree as ET


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


@pytest.mark.slow
@pytest.mark.asyncio(loop_scope="session")
async def test_json_response_is_parsed_into_an_object():
    action = CallApiAction()
    result = await action.execute({"url": "https://httpbin.org/json"}, _context())

    assert result.success is True
    assert result.output["content_type"] == "application/json"
    assert isinstance(result.output["body"], dict)
    assert "slideshow" in result.output["body"]  # httpbin.org/json's known shape


@pytest.mark.slow
@pytest.mark.asyncio(loop_scope="session")
async def test_xml_response_is_parsed_into_a_dict():
    action = CallApiAction()
    result = await action.execute({"url": "https://httpbin.org/xml"}, _context())

    assert result.success is True
    assert result.output["content_type"] in ("application/xml", "text/xml")
    assert isinstance(result.output["body"], dict)


@pytest.mark.slow
@pytest.mark.asyncio(loop_scope="session")
async def test_html_response_stays_as_raw_text():
    action = CallApiAction()
    result = await action.execute({"url": "https://httpbin.org/html"}, _context())

    assert result.success is True
    assert result.output["content_type"] == "text/html"
    assert isinstance(result.output["body"], str)
    assert "<html>" in result.output["body"].lower()


@pytest.mark.slow
@pytest.mark.asyncio(loop_scope="session")
async def test_query_params_are_appended_to_request():
    action = CallApiAction()
    result = await action.execute(
        {"url": "https://httpbin.org/get", "params": {"foo": "bar"}}, _context()
    )

    assert result.success is True
    assert result.output["body"]["args"]["foo"] == "bar"


@pytest.mark.slow
@pytest.mark.asyncio(loop_scope="session")
async def test_bearer_auth_sets_authorization_header():
    action = CallApiAction()
    result = await action.execute(
        {"url": "https://httpbin.org/headers", "auth": {"type": "bearer", "token": "abc123"}},
        _context(),
    )

    assert result.success is True
    assert result.output["body"]["headers"]["Authorization"] == "Bearer abc123"


@pytest.mark.slow
@pytest.mark.asyncio(loop_scope="session")
async def test_basic_auth_succeeds_against_matching_credentials():
    action = CallApiAction()
    result = await action.execute(
        {
            "url": "https://httpbin.org/basic-auth/testuser/testpass",
            "auth": {"type": "basic", "username": "testuser", "password": "testpass"},
        },
        _context(),
    )

    assert result.success is True
    assert result.output["status_code"] == 200


@pytest.mark.slow
@pytest.mark.asyncio(loop_scope="session")
async def test_apikey_auth_added_to_query_when_configured():
    action = CallApiAction()
    result = await action.execute(
        {
            "url": "https://httpbin.org/get",
            "auth": {"type": "apikey", "key": "api_key", "value": "xyz", "add_to": "query"},
        },
        _context(),
    )

    assert result.success is True
    assert result.output["body"]["args"]["api_key"] == "xyz"


@pytest.mark.asyncio(loop_scope="session")
async def test_missing_url_fails_without_network_call():
    action = CallApiAction()
    result = await action.execute({}, _context())

    assert result.success is False
    assert "url is required" in result.error


def test_xml_to_dict_collapses_repeated_tags_into_a_list():
    root = ET.fromstring("<root><item>A</item><item>B</item></root>")
    assert _xml_element_to_dict(root) == {"item": ["A", "B"]}


def test_xml_to_dict_leaf_element_collapses_to_its_text():
    root = ET.fromstring("<name>Cortex</name>")
    assert _xml_element_to_dict(root) == "Cortex"


def test_xml_to_dict_keeps_attributes():
    root = ET.fromstring('<item id="42">value</item>')
    assert _xml_element_to_dict(root) == {"@attributes": {"id": "42"}, "#text": "value"}
