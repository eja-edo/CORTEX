/**
 * Everything about M0 that can be checked without a bot token.
 *
 * Two of the three things the probe does are verifiable offline: the
 * payload we send must be well-formed, and the parser we will write for
 * `extra_data` must behave sanely on inputs we can imagine. Only the third
 * — what the gateway actually sends back — needs credentials. Splitting it
 * this way means the moment a token exists, the only unknown left is the
 * one that genuinely requires a live server.
 *
 * Run: npm run dry-run
 */

const { buildProbeForm, dissect } = require("./probe");
const { EMessageComponentType } = require("mezon-sdk");

let failures = 0;
function check(label, condition, detail) {
  if (condition) {
    console.log(`  ✅ ${label}`);
  } else {
    failures++;
    console.log(`  ❌ ${label}${detail ? ` — ${detail}` : ""}`);
  }
}

console.log("\n═══ 1. Payload gửi lên Mezon ═══\n");

const { embed, components } = buildProbeForm();
const payload = { t: "", embed, components };
console.log(JSON.stringify(payload, null, 2));

console.log("\n═══ 2. Kiểm tra hình dạng payload ═══\n");

const fields = embed[0].fields;
check("embed là array 1 phần tử", Array.isArray(embed) && embed.length === 1);
check("embed có title", typeof embed[0].title === "string" && embed[0].title.length > 0);
check("có đúng 7 field", fields.length === 7, `thấy ${fields.length}`);

const withInputs = fields.filter((f) => f.inputs);
check("cả 7 field đều mang `inputs`", withInputs.length === 7, `thấy ${withInputs.length}`);

const ids = withInputs.map((f) => f.inputs.id);
check(
  "id không trùng nhau",
  new Set(ids).size === ids.length,
  `ids=${JSON.stringify(ids)}`
);

// The reason every input type appears exactly once: one click then reveals
// how all of them serialise. A missing type here is a question M0 fails to
// answer, and a second round-trip to a live gateway later.
const typesPresent = new Set(withInputs.map((f) => f.inputs.type));
for (const [name, value] of [
  ["INPUT", EMessageComponentType.INPUT],
  ["SELECT", EMessageComponentType.SELECT],
  ["RADIO", EMessageComponentType.RADIO],
  ["DATEPICKER", EMessageComponentType.DATEPICKER],
]) {
  check(`có component type ${name} (${value})`, typesPresent.has(value));
}

const textarea = fields.find((f) => f.inputs?.id === "p_textarea");
check("textarea được đánh dấu", textarea?.inputs?.component?.textarea === true);

const numberField = fields.find((f) => f.inputs?.id === "p_number");
check("input number có type=number", numberField?.inputs?.component?.type === "number");

const prefilled = fields.find((f) => f.inputs?.id === "p_text");
check(
  "defaultValue đi được vào payload (nền tảng của form điền sẵn ở R1)",
  prefilled?.inputs?.component?.defaultValue === "giá trị mặc định"
);

const multi = fields.find((f) => f.inputs?.id === "p_radio_multi");
check("radio nhiều lựa chọn có max_options", multi?.inputs?.max_options === 3);
// The client gates multi-select on `options[0].name !== options[1].name`
// (EmbedOptionRatio.tsx). Identical names render a single-choice control
// with no error anywhere — the failure is silent, so it gets a test.
const multiNames = (multi?.inputs?.component ?? []).map((o) => o.name);
check(
  "radio nhiều: name của 2 option đầu phải KHÁC nhau",
  multiNames.length > 1 && multiNames[0] !== multiNames[1],
  `names=${JSON.stringify(multiNames)}`
);
const single = fields.find((f) => f.inputs?.id === "p_radio");
const singleNames = (single?.inputs?.component ?? []).map((o) => o.name);
check(
  "radio đơn: không đặt name (⇒ chọn một)",
  singleNames.every((n) => n === undefined),
  `names=${JSON.stringify(singleNames)}`
);

const dateField = fields.find((f) => f.inputs?.id === "p_date");
check("datepicker có mặt", dateField?.inputs?.type === EMessageComponentType.DATEPICKER);

const btns = components[0].components;
check("có 2 button", btns.length === 2, `thấy ${btns.length}`);
check("button có id/type/component", btns.every((b) => b.id && b.type && b.component));
check("button type = BUTTON(1)", btns.every((b) => b.type === EMessageComponentType.BUTTON));

check(
  "payload serialize được (socket sẽ JSON hoá)",
  (() => {
    try {
      JSON.parse(JSON.stringify(payload));
      return true;
    } catch {
      return false;
    }
  })()
);

console.log("\n═══ 3. dissect() trên các dạng extra_data có thể gặp ═══\n");

// We do not know which of these the gateway sends. That is the point: the
// dissector must produce a usable answer for all of them rather than
// throwing on the ones we did not expect.
const candidates = [
  ['JSON phẳng', '{"p_text":"xin chào","p_number":"42"}'],
  ['JSON lồng theo component', '{"p_text":{"value":"xin chào"}}'],
  ['array', '[{"id":"p_text","value":"xin chào"}]'],
  ['form-urlencoded', "p_text=xin+chao&p_number=42"],
  ["chuỗi rỗng", ""],
  ["null", null],
];

for (const [label, raw] of candidates) {
  const d = dissect(raw);
  console.log(`  • ${label.padEnd(26)} → ${d.verdict}${d.keys ? ` keys=${JSON.stringify(d.keys)}` : ""}`);
  check(
    `   dissect không ném với "${label}"`,
    typeof d.verdict === "string" && "raw" in d
  );
}

console.log(
  failures === 0
    ? "\n✅ Toàn bộ phần kiểm tra được offline đã đạt. Còn lại đúng một ẩn số: extra_data thật.\n"
    : `\n❌ ${failures} kiểm tra thất bại.\n`
);
process.exit(failures === 0 ? 0 : 1);
