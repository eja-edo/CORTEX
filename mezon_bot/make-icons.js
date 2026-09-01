#!/usr/bin/env node
"use strict";

/**
 * Render command names as PNG icons, for uploading as clan icons in Mezon.
 *
 *   node make-icons.js                 # every registered command
 *   node make-icons.js switch_model    # just this one
 *   node make-icons.js --size 256 today tasks
 *
 * Why this exists: Mezon opens an icon picker as soon as someone types
 * `:`, and filters it as they keep typing. A clan icon named after each
 * command turns that picker into command autocomplete — see the icon form
 * in `commands/registry.js`. The icons have to exist first, and drawing
 * eleven of them by hand is eleven chances to get a name subtly wrong.
 *
 * The name is what makes a command run; the picture only has to make the
 * right row easy to spot in a grid. That is why the text is rendered big
 * and the background colour is derived from the name — at picker size a
 * dozen dark squares of small white text are indistinguishable, and colour
 * is the thing the eye sorts on before it reads.
 *
 * SVG rasterised through `@resvg/resvg-js`, the same path `mezon/
 * tableRender.js` already uses — no browser, and no system library like
 * libvips to install.
 */

const fs = require("node:fs");
const path = require("node:path");
const { Resvg } = require("@resvg/resvg-js");

const COMMANDS_DIR = path.join(__dirname, "src", "commands");
const DEFAULT_OUT_DIR = path.join(__dirname, "icons");
const DEFAULT_SIZE = 128;

/** Padding as a fraction of the canvas. Mezon crops nothing, but an icon
 *  whose glyphs touch the edge reads as clipped at picker size. */
const PADDING_RATIO = 0.12;

/** Mean advance width of bold DejaVu/Liberation Sans, in ems.
 *
 *  Node has no font-metrics API without pulling in a canvas library, so
 *  this is measured-by-eye rather than computed — the same trade
 *  `tableRender.js` makes for its column widths. It only sets the font
 *  size, and it errs small: a name that ends up slightly narrower than the
 *  box is fine, one that overflows is not. */
const CHAR_WIDTH_EM = 0.62;

const LINE_HEIGHT_EM = 1.12;

/** Distance from the middle of a line of text down to its baseline, in
 *  ems. `dominant-baseline` would say this declaratively but resvg's
 *  support for it is partial, so the baseline is placed by hand. */
const BASELINE_DROP_EM = 0.35;

/**
 * Every command the bot registers, found by reading the directory rather
 * than by listing names here.
 *
 * A hardcoded list would be a second copy of the registry, and the copy
 * would be wrong the first time someone adds a command — silently, because
 * a missing icon looks exactly like an icon nobody made yet.
 */
function discoverCommandNames() {
  const names = new Set();

  for (const file of fs.readdirSync(COMMANDS_DIR)) {
    if (!file.endsWith(".js")) continue;

    const exported = require(path.join(COMMANDS_DIR, file));
    for (const value of Object.values(exported)) {
      // A command is an object with a name and something to run. Anything
      // else in these files (the registry class, helpers) fails this.
      if (value && typeof value === "object" && typeof value.name === "string" && typeof value.run === "function") {
        names.add(value.name);
      }
    }
  }

  return [...names].sort();
}

/** FNV-1a. Only used for names that are not commands — see `hueFor`. */
function hashHue(name) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < name.length; i += 1) {
    hash ^= name.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash % 360;
}

/**
 * Hue from the name's slot in the whole command roster, so the colours are
 * spread as far apart as eleven colours can be.
 *
 * Hashing the name was the first attempt and it failed its own purpose:
 * `inbox` landed on 235° and `today` on 238°, three degrees apart and
 * indistinguishable, with `new` a few degrees further into the same blue.
 * A hash spreads *values*, which is not the same as spreading them *where
 * a human can tell them apart*.
 *
 * The roster is read from disk every run, not from the command line, which
 * is what keeps `make-icons.js switch_model` and a full run in agreement —
 * one name's colour must not depend on which other names were asked for in
 * the same invocation.
 *
 * The trade: adding a twelfth command shifts every hue. That is a real
 * cost and it is the cheap one — the icon's *name* is what makes a command
 * run, so a re-run whose colours moved is cosmetic churn, fixed by
 * re-uploading or simply ignored.
 */
function hueFor(name, roster) {
  const index = roster.indexOf(name);
  if (index === -1) return hashHue(name);
  return Math.round((index * 360) / roster.length);
}

/** HSL → hex, written out because usvg's colour parsing is the one thing
 *  in this pipeline not worth betting the output on. */
function hslToHex(h, s, l) {
  const chroma = (1 - Math.abs(2 * l - 1)) * s;
  const secondary = chroma * (1 - Math.abs(((h / 60) % 2) - 1));
  const match = l - chroma / 2;

  const sector = Math.floor(h / 60) % 6;
  const [r, g, b] = [
    [chroma, secondary, 0],
    [secondary, chroma, 0],
    [0, chroma, secondary],
    [0, secondary, chroma],
    [secondary, 0, chroma],
    [chroma, 0, secondary],
  ][sector];

  const channel = (v) =>
    Math.round((v + match) * 255)
      .toString(16)
      .padStart(2, "0");

  return `#${channel(r)}${channel(g)}${channel(b)}`;
}

/** `switch_model` → ["switch", "model"].
 *
 *  Splitting on the separator rather than wrapping blind: the word break
 *  the author already wrote is a better one than any width calculation
 *  would find, and it is the difference between two readable words and
 *  `switch_m` / `odel`. */
function toLines(name) {
  return name.split(/[_-]+/).filter(Boolean);
}

function escapeXml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function buildSvg(name, size, roster) {
  const lines = toLines(name);
  const pad = size * PADDING_RATIO;
  const box = size - pad * 2;

  const longest = lines.reduce((max, line) => Math.max(max, line.length), 0);
  const byWidth = box / (longest * CHAR_WIDTH_EM);
  const byHeight = box / (lines.length * LINE_HEIGHT_EM);
  const fontSize = Math.min(byWidth, byHeight);

  const lineHeight = fontSize * LINE_HEIGHT_EM;
  const centre = size / 2;
  const firstLineCentre = centre - ((lines.length - 1) * lineHeight) / 2;

  const hue = hueFor(name, roster);
  const background = hslToHex(hue, 0.55, 0.36);

  const text = lines
    .map((line, index) => {
      const y = firstLineCentre + index * lineHeight + fontSize * BASELINE_DROP_EM;
      return (
        `<text x="${centre}" y="${y.toFixed(2)}" text-anchor="middle" ` +
        `font-family="DejaVu Sans, Liberation Sans, sans-serif" font-weight="bold" ` +
        `font-size="${fontSize.toFixed(2)}" fill="#ffffff">${escapeXml(line)}</text>`
      );
    })
    .join("");

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">` +
    `<rect width="${size}" height="${size}" rx="${(size * 0.18).toFixed(2)}" fill="${background}"/>` +
    text +
    `</svg>`
  );
}

function parseArgs(argv) {
  const names = [];
  let size = DEFAULT_SIZE;
  let outDir = DEFAULT_OUT_DIR;

  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--size") {
      size = Number(argv[i + 1]);
      i += 1;
    } else if (argv[i] === "--out") {
      outDir = path.resolve(argv[i + 1]);
      i += 1;
    } else {
      names.push(argv[i]);
    }
  }

  if (!Number.isFinite(size) || size < 16 || size > 1024) {
    throw new Error(`--size phải là số trong khoảng 16..1024, nhận được: ${size}`);
  }

  return { names, size, outDir };
}

function main() {
  const { names, size, outDir } = parseArgs(process.argv.slice(2));
  const targets = names.length ? names : discoverCommandNames();

  fs.mkdirSync(outDir, { recursive: true });

  const roster = discoverCommandNames();
  const known = new Set(roster);
  for (const name of targets) {
    const png = new Resvg(buildSvg(name, size, roster)).render().asPng();
    const file = path.join(outDir, `${name}.png`);
    fs.writeFileSync(file, png);

    // Flagged, not refused: rendering a name no command answers to is a
    // legitimate thing to want (a new command not written yet), but it is
    // also exactly what a typo looks like, and an icon whose name is a
    // typo is one nobody can explain later.
    const warning = known.has(name) ? "" : "   ⚠️ chưa có lệnh nào tên này";
    console.log(`  ${path.relative(process.cwd(), file)}  ${size}×${size}  ${(png.length / 1024).toFixed(1)} KB${warning}`);
  }

  console.log(`\n${targets.length} icon → ${path.relative(process.cwd(), outDir)}/`);
  console.log("Tải lên: Mezon → clan settings → Emoji → thêm, ĐẶT TÊN ĐÚNG BẰNG TÊN FILE.");
}

main();
