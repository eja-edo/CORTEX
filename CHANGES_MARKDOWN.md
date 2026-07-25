# Markdown Rendering — Bug fixes & Refactoring

## Kiến trúc mới

```
frontend/src/utils/markdown/
  config.ts          # MARKDOWN_IT_OPTIONS + danh sách allowed tags/attrs (1 nguồn duy nhất)
  renderToHtml.ts     # renderMarkdownToSanitizedHtml() + renderInlineMarkdownToHtml()
  blockParser.ts      # parseMarkdownToBlocks() — parse → block model cho editor
  __tests__/          # 78 test case cover toàn bộ basic syntax

backend/app/services/
  markdown_config.py  # build_markdown_renderer() — mirror frontend config
  notes.py            # dùng markdown_config.py, thêm breaks: true
```

## Bug → Fix mapping

| # | Bug | Vị trí cũ | Fix |
|---|-----|-----------|-----|
| 1 | Editor chỉ nhận H1-H3 | `blockParser.ts:370-376` `BlockRenderer.tsx:28-31` `HeadingBlock.tsx:11` | Thêm heading_4/5/6 vào switch, bỏ hardcode `\|\| 3`, CSS có sẵn |
| 2 | Setext heading (`===` / `---`) không hoạt động | `blockParser.ts` | `extractList`/`extractListItem` đọc token `heading_open` (cùng token type với ATX) từ `md.parse()` |
| 3 | Backend thiếu `breaks: true` | `notes.py:49` | Dùng `build_markdown_renderer()` từ `markdown_config.py` với `breaks: True` |
| 4 | ConversationDetail không render markdown | `ConversationDetail.tsx:46-83` | Thay `<p>{message.content}</p>` → `dangerouslySetInnerHTML` qua `renderMarkdownToSanitizedHtml` |
| 5 | Link title bị mất trong inline editor | `useRichTextBlock.ts:21` | `inlineMdToHtml` delegate sang `renderInlineMarkdownToHtml` dùng `md.renderInline()` thay vì regex |
| 6 | `\*` không unescape trong inline editor | `useRichTextBlock.ts` | markdown-it tự xử lý escape |
| 7 | Reference-style link không hoạt động | `blockParser.ts` | `md.render()` resolve reference link; content giữ nguyên syntax để editor re-render |
| 8 | Image không hỗ trợ title | `blockParser.ts:403,431` `ImageBlock.tsx:23` | Đọc từ token `image.attrGet('title')` + ghi lại vào `content` |
| 9 | Linking image không unwrap | `ImageBlock.tsx:23` | `findWrappingLink` quét children inline cho `link_open→image→link_close` |
| 10 | Loose list item bị tách block | `extractListContent:53-83` | Rework dùng `extractListItem` đọc token stream, paragraph thứ 2+ push vào `children` |
| 11 | Indent ≥4 spaces trong list thành code block | Cùng vị trí #10 | `fence`/`code_block` token trong item được push vào `itemChildren` |

## Files changed

**New files:**
- `frontend/src/utils/markdown/config.ts`
- `frontend/src/utils/markdown/renderToHtml.ts`
- `frontend/src/utils/markdown/blockParser.ts`
- `backend/app/services/markdown_config.py`

**Modified files:**
- `frontend/src/components/AskAI.tsx` — dùng shared util thay vì MarkdownIt+DOMPurify local
- `frontend/src/components/ConversationDetail.tsx` — render markdown cho user+assistant message
- `frontend/src/components/NoteSidebar.tsx` — dùng `renderMarkdownToSanitizedHtml` + sanitize
- `frontend/src/hooks/useRichTextBlock.ts` — `inlineMdToHtml` delegate sang `renderInlineMarkdownToHtml`
- `frontend/src/components/editor/BlockRenderer.tsx` — thêm heading_4/5/6
- `frontend/src/components/editor/blocks/HeadingBlock.tsx` — hỗ trợ level 1-6
- `frontend/src/types/editor.ts` — thêm `order?: number` trong `BlockMeta`
- `frontend/src/utils/markdownParser.ts` — re-export từ `blockParser.ts`
- `frontend/vite.config.ts` — thêm test config (jsdom, vitest)
- `frontend/package.json` — thêm test scripts
- `backend/app/services/notes.py` — dùng `build_markdown_renderer()`

## Test suite

78 test case trong 4 files:
- `shared-config.spec.ts` — config + drift detector
- `renderToHtml.spec.ts` — full basic syntax (30 tests)
- `inlineEditor.spec.ts` — inline rendering (12 tests)
- `blockParser.spec.ts` — block model parser (24 tests)

Run: `cd frontend && npm test`

## Chi chú

- `<details>` toggle: không hỗ trợ qua markdown với `html: false` (như code cũ). Toggle block chỉ tạo được qua editor UI (slash menu), đây là limitation có chủ đích vì bảo mật.
- Reference-style link trong block parser: content giữ nguyên `[text][1]` (không resolve). Resolve chỉ xảy ra ở render path (`renderMarkdownToSanitizedHtml`). Đây là behavior đúng — editor muốn giữ nguyên markdown source để người dùng edit.
