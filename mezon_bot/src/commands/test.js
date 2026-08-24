"use strict";

/**
 * `*test [svg|csv|embed]` — sends a sample so rendering can be judged on
 * the real client instead of debated in the abstract.
 *
 * `*test` (no argument) sends a real AI answer, verbatim, that a user
 * actually got back from asking "cho ví dụ cú pháp markdown" — headings,
 * bold/italic/strikethrough, a table, fenced code, blockquote, lists, a
 * task list, a link, an image, a horizontal rule. Sent through
 * `splitMezonContent` exactly as production does, with no other
 * processing — see `mezon/markdown.js`'s file docstring for why this
 * bot stopped translating the AI's Markdown into Mezon's own styling
 * vocabulary and just forwards the text as written.
 *
 * `*test svg` / `*test csv` / `*test embed` send a fixed sample table
 * through `mezon/tableRender.js`'s alternative renderers — image (PNG,
 * rasterised from SVG), file (CSV), and `InteractiveBuilder` embed
 * fields — kept as a standing comparison for anything that genuinely
 * needs a table as its own artifact (a downloadable CSV, a report
 * screenshot) rather than as part of the AI's own running text. None of
 * these are on the production reply path; `*test` above is.
 *
 * `svg` uploads to MinIO (`mezon/storage.js`) rather than sending a
 * `data:` URI: the PNG's base64 (~10KB) disconnected the socket every
 * time it was tried inline — the Mezon realtime gateway appears to cap
 * total message size well below that. `csv` stays on a `data:` URI; the
 * CSV is a few hundred bytes and has sent fine that way since the
 * attachment-encoding fix in `mezon/attachment.js`, so it needs no extra
 * infrastructure. If storage isn't configured (`MINIO_*` unset — normal
 * outside dev, since this command exists purely for manual comparison),
 * `svg` replies with what's missing instead of throwing.
 *
 * No `requiresLink`, no call to Cortex at all: this is purely local
 * rendering, so it works even against an account that has never linked.
 */

const { splitMezonContent } = require("../mezon/markdown");
const { tableToPng, tableToCsv, toDataUri, tableToEmbedFields } = require("../mezon/tableRender");
const { normalizeAttachment } = require("../mezon/attachment");
const { StorageNotConfiguredError } = require("../mezon/storage");
const { text, notice } = require("../mezon/embed");

const SAMPLE_MARKDOWN = "### Các ví dụ cú pháp Markdown\n\nDưới đây là danh sách các cú pháp Markdown phổ biến nhất được chia theo nhóm:\n\n---\n\n#### 1. Định dạng văn bản (Text Formatting)\n| Cú pháp | Kết quả |\n| :--- | :--- |\n| `**Chữ đậm**` | **Chữ đậm** |\n| `*Chữ nghiêng*` hoặc `_Chữ nghiêng_` | *Chữ nghiêng* |\n| `~~Chữ gạch ngang~~` | ~~Chữ gạch ngang~~ |\n| `***Đậm và nghiêng***` | ***Đậm và nghiêng*** |\n\n---\n\n#### 2. Tiêu đề (Headings)\nSử dụng dấu `#` để tạo các cấp độ tiêu đề (từ 1 đến 6):\n\n```markdown\n# Tiêu đề cấp 1 (H1)\n## Tiêu đề cấp 2 (H2)\n### Tiêu đề cấp 3 (H3)\n#### Tiêu đề cấp 4 (H4)\n```\n\n---\n\n#### 3. Danh sách (Lists)\n\n**Danh sách không thứ tự (Unordered List):**\n* Sử dụng dấu `*`, `-` hoặc `+`\n    * Mục con 1\n    * Mục con 2\n\n**Danh sách có thứ tự (Ordered List):**\n1. Mục thứ nhất\n2. Mục thứ hai\n    1. Mục con của thứ hai\n    2. Mục con khác\n\n---\n\n#### 4. Trích dẫn & Mã nguồn (Blockquotes & Code)\n\n**Trích dẫn (Blockquote):**\n> Đây là một đoạn trích dẫn.\n> Có thể chứa nhiều dòng.\n\n**Mã nguồn (Code):**\n* **Code inline (trên cùng 1 dòng):** Dùng dấu backtick `` `code` ``. Ví dụ: Hãy gõ `print(\"Hello\")` để bắt đầu.\n* **Code block (khối mã):** Dùng 3 dấu backtick:\n\n```python\ndef hello_world():\n    print(\"Hello, Markdown!\")\n```\n\n---\n\n#### 5. Đường dẫn & Hình ảnh (Links & Images)\n\n**Liên kết (Link):**\n`[Tên hiển thị](https://www.google.com)` → [Tên hiển thị](https://www.google.com)\n\n**Hình ảnh (Image):**\n`![Mô tả ảnh](https://url-hinh-anh.jpg)`\n\n---\n\n#### 6. Bảng (Tables)\nSử dụng dấu gạch đứng `|` và dấu gạch ngang `-` để phân chia cột và hàng:\n\n```markdown\n| Cột 1 | Cột 2 | Cột 3 |\n| :--- | :---: | ---: |\n| Trái | Giữa | Phải |\n| Dữ liệu | Dữ liệu | Dữ liệu |\n```\n\n---\n\n#### 7. Các ký tự đặc biệt (Task List & Horizontal Rule)\n\n**Danh sách công việc (Task List):**\n- [x] Việc đã hoàn thành\n- [ ] Việc chưa làm\n- [ ] Việc đang chờ\n\n**Đường kẻ ngang (Horizontal Rule):**\nSử dụng `---` hoặc `***` để tạo một đường kẻ ngang phân cách.\n\n---\n\nBạn muốn mình lưu danh sách này vào Note để tiện tra cứu sau này không?";

// Independent of SAMPLE_MARKDOWN — the "svg"/"csv"/"embed" variants below
// compare table *rendering strategies* on fixed sample data, nothing to
// do with the AI's own running text.
const SAMPLE_TABLE_ROWS = [
  ["Tên", "Trạng thái", "Ghi chú"],
  ["An", "Đang làm", "Cần hoàn thành trước thứ 6 tuần này"],
  ["Bình", "Xong", "OK"],
];

const testCommand = {
  name: "test",
  description: "Gửi mẫu markdown thô, hoặc `*test svg`/`*test csv`/`*test embed` để thử render bảng riêng",
  usage: "*test [svg|csv|embed]",
  requiresLink: false,

  async run({ args, reply, storage }) {
    const variant = (args ?? "").trim().toLowerCase();

    if (variant === "embed") {
      await reply(notice("Bảng dưới dạng embed fields", null, { fields: tableToEmbedFields(SAMPLE_TABLE_ROWS) }));
      return;
    }

    if (variant === "svg") {
      const png = tableToPng(SAMPLE_TABLE_ROWS);
      let url;
      try {
        url = await storage.uploadPublicObject(png, { key: `${Date.now()}-table.png`, contentType: "image/png" });
      } catch (err) {
        const reason = err instanceof StorageNotConfiguredError ? err.message : `Upload MinIO thất bại: ${err.message}`;
        await reply(text(`⚠️ Không gửi được ảnh bảng: ${reason}`));
        return;
      }
      await reply(
        text("Bảng dưới dạng ảnh PNG (render từ SVG, host qua MinIO):"),
        [normalizeAttachment({ url, filetype: "image/png", filename: "table.png" })]
      );
      return;
    }

    if (variant === "csv") {
      const csv = tableToCsv(SAMPLE_TABLE_ROWS);
      await reply(
        text("Bảng dưới dạng file CSV (data: URI — có thể Mezon không chấp nhận, đây là thử nghiệm):"),
        [normalizeAttachment({ url: toDataUri(csv, "text/csv"), filetype: "text/csv", filename: "table.csv" })]
      );
      return;
    }

    for (const chunk of splitMezonContent(SAMPLE_MARKDOWN)) {
      await reply(chunk);
    }
  },
};

module.exports = { testCommand };
