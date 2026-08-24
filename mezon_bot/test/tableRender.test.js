"use strict";

/**
 * Tests for the SVG/CSV table renderers (F2 alternative table rendering).
 * These are the "compare against the plain-text table" experiment — see
 * the file docstring in `src/mezon/tableRender.js` for why they exist and
 * why they go out as `data:` URIs.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { tableToSvg, tableToCsv, tableToPng, toDataUri, tableToEmbedFields } = require("../src/mezon/tableRender");

// Written as an escape, not typed as a literal character — see
// markdown.js's NBSP constant for why (invisible, so a literal is
// indistinguishable from an accidental empty string on re-save).
const ZERO_WIDTH_SPACE = "\u200B";

const SAMPLE_ROWS = [
  ["Tên", "Trạng thái"],
  ["An", "Đang làm"],
  ["Bình", "Xong"],
];

test("tableToSvg produces a well-formed <svg> root with a computed width and height", () => {
  const svg = tableToSvg(SAMPLE_ROWS);
  assert.match(svg, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg" width="\d+" height="\d+"/);
  assert.match(svg, /<\/svg>$/);
  const widthMatch = svg.match(/width="(\d+)"/);
  const heightMatch = svg.match(/height="(\d+)"/);
  assert.ok(Number(widthMatch[1]) > 0);
  // One row of fixed height per data row, header included.
  assert.equal(Number(heightMatch[1]), SAMPLE_ROWS.length * 28);
});

test("tableToSvg includes every cell's text content", () => {
  const svg = tableToSvg(SAMPLE_ROWS);
  for (const row of SAMPLE_ROWS) {
    for (const cell of row) {
      assert.ok(svg.includes(`>${cell}<`), `expected "${cell}" to appear as SVG text content`);
    }
  }
});

test("tableToSvg escapes XML-special characters in cell content", () => {
  const svg = tableToSvg([["A & B"], ["<script>alert(1)</script>"]]);
  assert.ok(!svg.includes("<script>"), "a literal tag in cell content must not become real SVG markup");
  assert.ok(svg.includes("&amp;"));
  assert.ok(svg.includes("&lt;script&gt;"));
});

test("tableToSvg styles the header row distinctly from data rows", () => {
  const svg = tableToSvg(SAMPLE_ROWS);
  assert.match(svg, /font-weight="bold"/, "the header row's text must be bold");
  // Exactly one bold cell per header column.
  const boldCount = (svg.match(/font-weight="bold"/g) || []).length;
  assert.equal(boldCount, SAMPLE_ROWS[0].length);
});

test("tableToCsv round-trips header and rows with RFC 4180 quoting for a comma inside a cell", () => {
  const csv = tableToCsv([
    ["Tên", "Ghi chú"],
    ["An", "Cần làm, gấp"],
  ]);
  assert.equal(csv, 'Tên,Ghi chú\nAn,"Cần làm, gấp"\n');
});

test("tableToCsv quotes a cell containing a literal double quote by doubling it", () => {
  const csv = tableToCsv([["Tên"], [`Nói "xin chào"`]]);
  assert.equal(csv, 'Tên\n"Nói ""xin chào"""\n');
});

test("tableToPng rasterises to a real PNG buffer (magic bytes, non-trivial size)", () => {
  // The whole reason this function exists over just sending tableToSvg's
  // output directly — see the file docstring — is that a raw SVG came
  // through as a downloadable file, not an inline image. A real PNG is
  // what a chat client is actually willing to preview.
  const png = tableToPng(SAMPLE_ROWS);
  assert.ok(Buffer.isBuffer(png));
  assert.equal(png[0], 0x89, "PNG magic byte");
  assert.equal(png.toString("ascii", 1, 4), "PNG");
  assert.ok(png.length > 100, "a real rendered table should be more than a trivial handful of bytes");
});

test("toDataUri round-trips arbitrary UTF-8 content through base64", () => {
  const original = "Xin chào — dữ liệu có dấu tiếng Việt";
  const uri = toDataUri(original, "text/csv");
  assert.match(uri, /^data:text\/csv;base64,/);
  const b64 = uri.slice(uri.indexOf(",") + 1);
  const decoded = Buffer.from(b64, "base64").toString("utf8");
  assert.equal(decoded, original);
});

test("toDataUri accepts a Buffer directly, for binary output like tableToPng's", () => {
  const png = tableToPng(SAMPLE_ROWS);
  const uri = toDataUri(png, "image/png");
  const decoded = Buffer.from(uri.slice(uri.indexOf(",") + 1), "base64");
  assert.deepEqual(decoded, png);
});

test("toDataUri uses the mime type it's given", () => {
  const uri = toDataUri("<svg></svg>", "image/svg+xml");
  assert.match(uri, /^data:image\/svg\+xml;base64,/);
});

test("tableToEmbedFields opens with a standalone header row (labels as name, blank value), then one field per data cell with a blank name, a non-inline row-break field between every row", () => {
  const fields = tableToEmbedFields(SAMPLE_ROWS);
  // 2 header fields + row-break + (2 data rows × 2 columns, one more
  // row-break between them) = 8 fields.
  assert.equal(fields.length, 8);
  // The header row: bold labels, nothing under them.
  assert.deepEqual(fields[0], { name: "Tên", value: ZERO_WIDTH_SPACE, inline: true });
  assert.deepEqual(fields[1], { name: "Trạng thái", value: ZERO_WIDTH_SPACE, inline: true });
  // A non-inline field forces Mezon to start a new visual row here,
  // regardless of column count — see the function's own docstring for
  // why this is load-bearing, not decorative, confirmed live.
  assert.deepEqual(fields[2], { name: ZERO_WIDTH_SPACE, value: ZERO_WIDTH_SPACE, inline: false });
  // First data row — no label repeated, the header above already said it.
  assert.deepEqual(fields[3], { name: ZERO_WIDTH_SPACE, value: "An", inline: true });
  assert.deepEqual(fields[4], { name: ZERO_WIDTH_SPACE, value: "Đang làm", inline: true });
  assert.deepEqual(fields[5], { name: ZERO_WIDTH_SPACE, value: ZERO_WIDTH_SPACE, inline: false });
  // Second data row — same blank-name treatment, not just the first.
  assert.deepEqual(fields[6], { name: ZERO_WIDTH_SPACE, value: "Bình", inline: true });
  assert.deepEqual(fields[7], { name: ZERO_WIDTH_SPACE, value: "Xong", inline: true });
});

test("tableToEmbedFields never adds a row-break after the very last row", () => {
  const fields = tableToEmbedFields(SAMPLE_ROWS);
  assert.notEqual(fields.at(-1).inline, false, "the last field must be a real data cell, not a trailing row-break");
});

test("a 2-column table gets exactly one row-break per row boundary, not tied to any particular column count", () => {
  const fields = tableToEmbedFields([["A", "B"], ["1", "2"], ["3", "4"], ["5", "6"]]);
  const breakCount = fields.filter((f) => f.inline === false).length;
  // header + 3 data rows = 4 rows total, 3 boundaries between them.
  assert.equal(breakCount, 3);
});

test("tableToEmbedFields substitutes a zero-width space for an empty cell, never a blank value", () => {
  const fields = tableToEmbedFields([["Tên", "Ghi chú"], ["An", ""]]);
  // fields[0..1] are the header row, fields[2] is the row-break between
  // header and data, fields[3..4] are the one data row — its second
  // cell ("") is the empty one under test.
  assert.equal(fields[4].name, ZERO_WIDTH_SPACE);
  assert.equal(fields[4].value, ZERO_WIDTH_SPACE);
  assert.notEqual(fields[4].value, "", "must not be a truly empty string");
});
