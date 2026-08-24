"use strict";

/**
 * Alternative table renderers, for comparison against the plain-text
 * approach in `markdown.js` — see `*test` (commands/test.js), which can
 * send any of the three so they can be judged side by side on the real
 * client instead of debated in the abstract.
 *
 * Both render to an image/file that has to reach the user as a real,
 * fetchable URL — `ApiMessageAttachment.url` (see `markdown.js`'s
 * docstring on why images ride separately from `t`/`mk`) is a link Mezon's
 * own servers fetch, not a place to embed bytes. Neither of these has
 * anywhere to be *hosted*: this bot has no public URL (its `/internal/
 * deliver` server binds `127.0.0.1` on purpose — see server.js — and nothing
 * else in this repo serves arbitrary generated files to the internet). Both
 * therefore go out as `data:` URIs instead, which costs nothing to try and
 * needs no new infrastructure — but it is a genuine experiment, not a
 * known-working path: some chat clients refuse `data:` URLs for
 * attachments outright (size limits, a fetcher that only speaks http(s)).
 * If Mezon does too, the next step is real hosting (this repo already runs
 * MinIO for asset storage — see `infrastructure/docker-compose.yml` — which
 * is the obvious place), not a smarter data URI.
 *
 * `tableToSvg` builds SVG as text — no canvas/font-rendering dependency
 * needed to produce it, same as the rest of this file builds text. The
 * `svg-table` package the request named turns out to need an actual DOM to
 * run against (`d3.select(container)`, a browser library, not a
 * string-in-string-out one) and doesn't declare `d3` as a runtime
 * dependency to begin with — pulling in `jsdom` just to hand it a
 * container was worse than the ~40 lines it takes to emit
 * `<rect>`/`<text>` elements directly.
 *
 * But SVG itself turned out not to be the attachment worth sending: it
 * came through as a downloadable file rather than an inline preview.
 * That is consistent with a security posture most chat clients take on
 * purpose (Discord, Slack, Telegram all do the same) — an SVG can carry
 * `<script>`/event-handler attributes, so treating it as "just an image"
 * would make image attachments a code-execution vector. `tableToPng`
 * rasterises the same SVG through `@resvg/resvg-js` (a native, no-browser
 * SVG renderer — chosen over `sharp` for having no separate system
 * library like libvips to install) into a real PNG, which every client
 * does trust as an image. The SVG builder stays — it's what feeds the
 * rasteriser, and remains useful standalone for anything that *can* take
 * inline SVG.
 */

const { stringify } = require("csv-stringify/sync");
const { Resvg } = require("@resvg/resvg-js");

// Written as an escape, not typed as a literal character — invisible by
// design, so a literal would be indistinguishable from an accidental
// empty string on re-save. See markdown.js's NBSP constant for the same
// reasoning.
const ZERO_WIDTH_SPACE = "\u200B";

const SVG_FONT_FAMILY = "monospace";
const SVG_FONT_SIZE = 14;
// Monospace at this size: close enough for column sizing without an actual
// font-metrics lookup, which Node has no built-in way to do without a
// canvas library. Cells are left-aligned within their column, so being a
// little generous here (versus exactly wrong) just adds harmless padding.
const SVG_CHAR_WIDTH = SVG_FONT_SIZE * 0.62;
const SVG_ROW_HEIGHT = 28;
const SVG_CELL_PAD_X = 12;
const SVG_HEADER_FILL = "#2b2f3a";
const SVG_HEADER_TEXT = "#f5f5f5";
const SVG_ROW_FILL = "#ffffff";
const SVG_ROW_ALT_FILL = "#f2f2f2";
const SVG_ROW_TEXT = "#1a1a1a";
const SVG_BORDER = "#c9c9c9";

function _escapeXml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** `rows[0]` is the header; the rest are data rows — same shape the
 *  markdown table parser produces (array of arrays of cell strings). */
function tableToSvg(rows) {
  const colCount = rows.reduce((max, row) => Math.max(max, row.length), 0);
  const colWidths = [];
  for (let c = 0; c < colCount; c++) {
    let widest = 0;
    for (const row of rows) widest = Math.max(widest, String(row[c] ?? "").length);
    colWidths[c] = Math.ceil(widest * SVG_CHAR_WIDTH) + SVG_CELL_PAD_X * 2;
  }
  const colX = [0];
  for (let c = 0; c < colCount; c++) colX.push(colX[c] + colWidths[c]);

  const totalWidth = colX[colCount];
  const totalHeight = rows.length * SVG_ROW_HEIGHT;

  const parts = [];
  rows.forEach((row, r) => {
    const y = r * SVG_ROW_HEIGHT;
    const isHeader = r === 0;
    const fill = isHeader ? SVG_HEADER_FILL : r % 2 === 0 ? SVG_ROW_FILL : SVG_ROW_ALT_FILL;
    const textFill = isHeader ? SVG_HEADER_TEXT : SVG_ROW_TEXT;
    parts.push(
      `<rect x="0" y="${y}" width="${totalWidth}" height="${SVG_ROW_HEIGHT}" fill="${fill}" stroke="${SVG_BORDER}" />`
    );
    for (let c = 0; c < colCount; c++) {
      const cellX = colX[c];
      const textY = y + SVG_ROW_HEIGHT / 2 + SVG_FONT_SIZE * 0.35;
      parts.push(
        `<text x="${cellX + SVG_CELL_PAD_X}" y="${textY}" font-family="${SVG_FONT_FAMILY}" font-size="${SVG_FONT_SIZE}" ` +
          `fill="${textFill}"${isHeader ? ' font-weight="bold"' : ""}>${_escapeXml(row[c])}</text>`
      );
      if (c > 0) {
        parts.push(`<line x1="${cellX}" y1="${y}" x2="${cellX}" y2="${y + SVG_ROW_HEIGHT}" stroke="${SVG_BORDER}" />`);
      }
    }
  });

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${totalWidth}" height="${totalHeight}" ` +
    `viewBox="0 0 ${totalWidth} ${totalHeight}">${parts.join("")}</svg>`
  );
}

/** `rows[0]` is the header — RFC 4180 quoting/escaping via `csv-stringify`,
 *  not hand-rolled, for the usual reasons hand-rolled CSV goes wrong
 *  (a comma or quote inside a cell). */
function tableToCsv(rows) {
  return stringify(rows);
}

/**
 * A table as `InteractiveBuilder` embed fields (`mezon/embed.js`'s
 * `notice()`/`FormBuilder.field()`) instead of monospace text — a
 * genuinely different rendering mechanism from everything else in this
 * file and `markdown.js`. `*ping` already uses it (`commands/basic.js`)
 * for its Bot/Cortex/Tài khoản status line, which is what prompted trying
 * it here: it's Mezon's own structured card UI (the field shape —
 * `{name, value, inline}` — is the same as Discord's embed fields), not
 * something this bot is hand-rendering and hoping stays aligned.
 *
 * One field *per cell*, `inline: true`, confirmed live on the real
 * client to lay out as a genuine grid — bold column labels, proportional
 * columns, and a long "Ghi chú" cell wraps inside its own column without
 * breaking alignment, none of which `markdown.js`'s table gets without
 * hand-built padding and NBSP.
 *
 * The header is its own standalone row of fields first — `name` is the
 * column label, `value` a zero-width space (a field needs *some* value;
 * see the empty-cell note below), which reads as a bold label with
 * nothing under it, i.e. a real header. Every data row after that has a
 * zero-width `name` instead: the field still occupies the same
 * name+value slot (so column alignment doesn't shift row to row), it
 * just shows nothing where a repeated label would have been. This
 * replaced an earlier version that put the column labels on the first
 * *data* row's own fields — visually close, but structurally the header
 * was one row's labels rather than a row of its own, which is what was
 * actually asked for.
 *
 * A zero-width, `inline: false` field is inserted after *every* row
 * (header included, except the very last row — nothing needs to follow
 * it) — confirmed live to be necessary, not decorative: Mezon wraps
 * inline fields onto a new visual row every 3 fields, a fixed count that
 * has nothing to do with how many columns a given table actually has.
 * A 3-column table happens to line up (every 3 fields *is* one row), so
 * this went unnoticed until a 2-column table was tested live: its data
 * rows drifted across the header's own column boundaries, because 2
 * fields per row never divides evenly into a 3-per-line wrap. An
 * `inline: false` field forces a line break at that exact point
 * regardless of field count — the same technique Discord embeds use for
 * the same reason, since Mezon's field shape is the same one.
 */
function tableToEmbedFields(rows) {
  const header = rows[0];
  const rowBreak = { name: ZERO_WIDTH_SPACE, value: ZERO_WIDTH_SPACE, inline: false };

  const fields = header.map((label) => ({ name: label, value: ZERO_WIDTH_SPACE, inline: true }));
  const dataRows = rows.slice(1);
  if (dataRows.length) fields.push(rowBreak);

  dataRows.forEach((row, rowIndex) => {
    header.forEach((_label, i) => {
      // An empty field value has been rejected outright by some
      // Discord-embed-shaped APIs — Mezon's own tolerance for it is
      // untested, so an empty cell gets a zero-width space instead of
      // risking the whole message failing to send over one blank cell.
      fields.push({ name: ZERO_WIDTH_SPACE, value: String(row[i] ?? "").trim() || ZERO_WIDTH_SPACE, inline: true });
    });
    if (rowIndex < dataRows.length - 1) fields.push(rowBreak);
  });

  return fields;
}

/** `rows[0]` is the header — builds the SVG via `tableToSvg` and
 *  rasterises it, so this is the version worth actually sending as an
 *  attachment (see the file docstring on why SVG itself wasn't). Returns
 *  a `Buffer`, not a string — `toDataUri` accepts one directly. */
function tableToPng(rows) {
  const svg = tableToSvg(rows);
  return new Resvg(svg).render().asPng();
}

function toDataUri(content, mimeType) {
  const bytes = Buffer.isBuffer(content) ? content : Buffer.from(content, "utf8");
  return `data:${mimeType};base64,${bytes.toString("base64")}`;
}

module.exports = { tableToSvg, tableToCsv, tableToPng, toDataUri, tableToEmbedFields };
