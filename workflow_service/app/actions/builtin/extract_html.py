from bs4 import BeautifulSoup, Tag

from app.actions.base import BaseAction, ActionContext, ActionResult


def _element_to_json(element: Tag) -> dict:
    """Đệ quy 1 phần tử BeautifulSoup thành cây JSON {tag, attributes, text|children}
    — không cần biết trước HTML có tag gì. 1 phần tử chỉ chứa đúng 1 text node (không
    có tag con) thì gộp thẳng vào "text" (khớp cách _xml_element_to_dict xử lý XML);
    có tag con (kể cả trộn lẫn text) thì giữ nguyên thứ tự trong "children"."""
    result: dict = {"tag": element.name}
    if element.attrs:
        result["attributes"] = dict(element.attrs)

    children: list = []
    has_tag_child = False
    for child in element.children:
        if isinstance(child, Tag):
            children.append(_element_to_json(child))
            has_tag_child = True
        else:
            text = str(child).strip()
            if text:
                children.append({"text": text})

    if not children:
        return result
    if not has_tag_child and len(children) == 1:
        result["text"] = children[0]["text"]
    else:
        result["children"] = children
    return result


class ExtractHtmlAction(BaseAction):
    """Trích xuất text/HTML/attribute/cây DOM (JSON) từ 1 chuỗi HTML bằng CSS
    selector — dùng để đọc tiếp dữ liệu HTML thô mà action.call_api trả về
    (hoặc bất kỳ bước nào khác trả về HTML), thay vì phải tự parse bằng tay."""

    @property
    def action_type(self) -> str:
        return "action.extract_html"

    @property
    def display_name(self) -> str:
        return "Trích xuất HTML"

    @property
    def description(self) -> str:
        return "Trích xuất nội dung từ HTML theo CSS selector (text/HTML/attribute/DOM JSON)"

    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "html": {
                    "type": "string",
                    "title": "HTML",
                    "description": "Chuỗi HTML nguồn, hỗ trợ template (vd {{steps.callApi.body}})"
                },
                "selector": {
                    "type": "string",
                    "title": "CSS Selector",
                    "description": "vd .class-name, #id, table tr td"
                },
                "extract": {
                    "type": "string",
                    "title": "Extract",
                    "enum": ["text", "html", "attribute", "dom"],
                    "description": "dom = cây JSON {tag, attributes, text|children} đệ quy toàn bộ phần tử, không cần biết trước cấu trúc tag",
                    "default": "text"
                },
                "attribute": {
                    "type": "string",
                    "title": "Attribute",
                    "description": "Bắt buộc khi extract = attribute, vd href, src"
                },
                "multiple": {
                    "type": "boolean",
                    "title": "Multiple",
                    "description": "Lấy tất cả phần tử khớp (mảng) thay vì chỉ phần tử đầu tiên",
                    "default": False
                }
            },
            "required": ["html", "selector"]
        }

    async def execute(self, config: dict, context: ActionContext) -> ActionResult:
        html = self.resolve_template(config.get("html", ""), context)
        selector = config.get("selector", "")
        extract_mode = config.get("extract", "text")
        attribute = config.get("attribute", "")
        multiple = bool(config.get("multiple", False))

        if not html:
            return ActionResult(success=False, output={}, error="html is required")
        if not selector:
            return ActionResult(success=False, output={}, error="selector is required")

        try:
            soup = BeautifulSoup(html, "html.parser")
            elements = soup.select(selector)
        except Exception as e:
            return ActionResult(success=False, output={}, error=f"Invalid selector: {str(e)}")

        def extract_value(el):
            if extract_mode == "dom":
                return _element_to_json(el)
            if extract_mode == "html":
                return str(el)
            if extract_mode == "attribute":
                return el.get(attribute, "")
            return el.get_text(strip=True)

        if multiple:
            values = [extract_value(el) for el in elements]
            return ActionResult(success=True, output={"count": len(values), "values": values})

        if not elements:
            return ActionResult(success=True, output={"found": False, "value": None})

        return ActionResult(success=True, output={"found": True, "value": extract_value(elements[0])})
