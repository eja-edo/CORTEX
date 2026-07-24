"""Shared markdown renderer configuration.

IMPORTANT: keep these options in sync with the frontend module
`frontend/src/utils/markdown/config.ts`. The frontend test
`shared-config.spec.ts` enforces the shape of the JSON-exported options
below, so any drift will fail the test suite.

Backend note previews are rendered through `_render_markdown_html` in
`app/services/notes.py`. If you add a new option here, mirror it in the
frontend file as well so server-side previews and in-browser rendering never
diverge.
"""

from markdown_it import MarkdownIt

# Single source of truth for the markdown-it configuration used to render
# note previews server-side.
MARKDOWN_IT_OPTIONS: dict[str, object] = {
    "html": False,
    "linkify": True,
    "typographer": True,
    "breaks": True,
}


def build_markdown_renderer() -> MarkdownIt:
    """Build a markdown-it instance with the project's shared options."""
    return MarkdownIt("commonmark", MARKDOWN_IT_OPTIONS)
