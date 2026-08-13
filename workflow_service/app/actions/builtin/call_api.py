import xml.etree.ElementTree as ET

import httpx

from app.actions.base import BaseAction, ActionContext, ActionResult


def _xml_element_to_dict(element: ET.Element) -> dict | str:
    """Minimal XML->dict conversion (stdlib only, no xmltodict dependency).
    Repeated child tags become a list; leaf elements with no children/attrs
    collapse to their text content directly, so a simple document reads as
    a plain dict instead of a wrapper-heavy tree."""
    result: dict = {}
    if element.attrib:
        result["@attributes"] = dict(element.attrib)

    children = list(element)
    if children:
        child_data: dict = {}
        for child in children:
            child_result = _xml_element_to_dict(child)
            if child.tag in child_data:
                if not isinstance(child_data[child.tag], list):
                    child_data[child.tag] = [child_data[child.tag]]
                child_data[child.tag].append(child_result)
            else:
                child_data[child.tag] = child_result
        result.update(child_data)
        return result

    text = (element.text or "").strip()
    if result:
        if text:
            result["#text"] = text
        return result
    return text


class CallApiAction(BaseAction):
    """Gọi HTTP API và tự parse response theo Content-Type, để dùng dữ liệu
    trả về ở bước sau trong workflow."""

    @property
    def action_type(self) -> str:
        return "action.call_api"

    @property
    def display_name(self) -> str:
        return "Gọi API"

    @property
    def description(self) -> str:
        return "Gọi HTTP API và tự parse response theo Content-Type (JSON/XML/HTML/text)"

    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "title": "URL",
                    "description": "URL đích, hỗ trợ template"
                },
                "method": {
                    "type": "string",
                    "title": "Method",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                    "default": "GET"
                },
                "params": {
                    "type": "object",
                    "title": "Query Params",
                    "default": {}
                },
                "auth": {
                    "type": "object",
                    "title": "Authorization",
                    "description": "type: none | bearer | basic | apikey",
                    "default": {"type": "none"}
                },
                "headers": {
                    "type": "object",
                    "title": "Headers",
                    "default": {}
                },
                "body": {
                    "type": "string",
                    "title": "Body",
                    "description": "Request body, hỗ trợ template — bỏ trống nếu method là GET"
                }
            },
            "required": ["url"]
        }

    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        url = self.resolve_template(config.get("url", ""), context)
        method = config.get("method", "GET").upper()
        headers = config.get("headers", {}) or {}
        params = config.get("params", {}) or {}
        auth = config.get("auth", {}) or {}
        body = self.resolve_template(config.get("body", ""), context)

        resolved_headers = {}
        for k, v in headers.items():
            resolved_headers[k] = self.resolve_template(v, context) if isinstance(v, str) else v

        resolved_params = {}
        for k, v in params.items():
            resolved_params[k] = self.resolve_template(v, context) if isinstance(v, str) else v

        request_auth = None
        auth_type = auth.get("type", "none")
        if auth_type == "bearer":
            token = self.resolve_template(auth.get("token", ""), context)
            if token:
                resolved_headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "basic":
            username = self.resolve_template(auth.get("username", ""), context)
            password = self.resolve_template(auth.get("password", ""), context)
            request_auth = (username, password)
        elif auth_type == "apikey":
            key_name = auth.get("key", "")
            key_value = self.resolve_template(auth.get("value", ""), context)
            if key_name:
                if auth.get("add_to") == "query":
                    resolved_params[key_name] = key_value
                else:
                    resolved_headers[key_name] = key_value

        if not url:
            return ActionResult(success=False, output={}, error="url is required")

        async with httpx.AsyncClient() as client:
            try:
                request_kwargs: dict = {"headers": resolved_headers, "timeout": 30.0}
                if body:
                    request_kwargs["content"] = body
                if resolved_params:
                    request_kwargs["params"] = resolved_params
                if request_auth:
                    request_kwargs["auth"] = request_auth

                response = await client.request(method, url, **request_kwargs)

                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                raw_body = response.text[:10000]

                if content_type == "application/json" or content_type.endswith("+json"):
                    try:
                        parsed_body = response.json()
                    except ValueError:
                        parsed_body = raw_body
                elif content_type in ("application/xml", "text/xml") or content_type.endswith("+xml"):
                    try:
                        parsed_body = _xml_element_to_dict(ET.fromstring(response.text))
                    except ET.ParseError:
                        parsed_body = raw_body
                else:
                    # text/html, text/plain, hoặc Content-Type khác/không rõ — giữ nguyên text.
                    # Parse DOM cho HTML (chọn phần tử theo selector) là việc lớn hơn,
                    # ngoài phạm vi node này.
                    parsed_body = raw_body

                return ActionResult(
                    success=True,
                    output={
                        "status_code": response.status_code,
                        "content_type": content_type or "unknown",
                        "body": parsed_body,
                        "raw_body": raw_body,
                    }
                )

            except httpx.HTTPError as e:
                return ActionResult(success=False, output={}, error=f"API call failed: {str(e)}")
