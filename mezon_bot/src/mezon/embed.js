"use strict";

/**
 * Building what the user sees.
 *
 * Wraps the SDK's `InteractiveBuilder`/`ButtonBuilder` rather than exposing
 * them, for the reason listed as a risk in the plan: the Mezon docs and the
 * SDK source already disagree, so the SDK is treated as a moving target and
 * kept behind one seam. When it moves, this file changes and nothing else
 * does.
 *
 * It also encodes the multi-select rule that cost a debugging round: the
 * client decides single vs multi by comparing the `name` of the first two
 * options (`EmbedOptionRatio.tsx`), so identical names silently produce a
 * single-choice control. `radioField` derives distinct names itself
 * instead of trusting callers to remember.
 */

const {
  InteractiveBuilder,
  ButtonBuilder,
  EButtonMessageStyle,
} = require("mezon-sdk");

const { actionId } = require("./actions");

const STYLE = EButtonMessageStyle;

/** Cortex brand-ish accent so bot messages are recognisable at a glance. */
const DEFAULT_COLOR = "#7c5cff";

class FormBuilder {
  constructor(title) {
    this.builder = new InteractiveBuilder(title);
    this.buttons = new ButtonBuilder();
    this.hasButtons = false;
    this.color = DEFAULT_COLOR;
  }

  description(text) {
    this.builder.setDescription(text);
    return this;
  }

  /** Read-only line. */
  field(name, value, inline = false) {
    this.builder.addField(name, value, inline);
    return this;
  }

  /**
   * Text input. `defaultValue` is not cosmetic: an untouched field is
   * absent from the submission entirely, so pre-filling is the only way an
   * edit form can tell "left as-is" from "cleared".
   */
  textInput(id, label, { placeholder, defaultValue, textarea, type, description } = {}) {
    this.builder.addInputField(
      id,
      label,
      placeholder,
      { defaultValue: defaultValue ?? "", textarea: Boolean(textarea), type: type ?? "text" },
      description
    );
    return this;
  }

  select(id, label, options, { selected, description } = {}) {
    this.builder.addSelectField(id, label, options, selected, description);
    return this;
  }

  /**
   * Radio group. Pass `multiple: true` for checkbox behaviour.
   *
   * The distinct-`name` derivation below is the whole reason this wrapper
   * exists rather than a direct `addRadioField` call — see the file
   * docstring. Single-choice deliberately sets no `name` at all, which is
   * what the client reads as "one group".
   */
  radio(id, label, options, { multiple = false, maxOptions, description } = {}) {
    const prepared = options.map((option, index) => ({
      label: option.label,
      value: option.value,
      description: option.description,
      style: option.style,
      disabled: option.disabled,
      ...(multiple ? { name: `${id}_${index}` } : {}),
    }));
    this.builder.addRadioField(
      id,
      label,
      prepared,
      description,
      multiple ? maxOptions ?? options.length : undefined
    );
    return this;
  }

  datePicker(id, label, description) {
    this.builder.addDatePickerField(id, label, description);
    return this;
  }

  button(id, label, style = STYLE.SECONDARY) {
    this.buttons.addButton(id, label, style);
    this.hasButtons = true;
    return this;
  }

  /** Returns a `ChannelMessageContent` ready for `send`/`update`. */
  build(text = "") {
    const embed = this.builder.build();
    embed.color = this.color;
    const content = { t: text, embed: [embed] };
    if (this.hasButtons) {
      content.components = [{ components: this.buttons.build() }];
    }
    return content;
  }
}

/** Plain text message. Kept here so no call site constructs `{ t }` by
 *  hand — the day that shape changes, it changes once. */
function text(body) {
  return { t: body };
}

/**
 * `tableRender.js`'s `tableToEmbedFields()` output (plain
 * `{name, value, inline}` data — `markdown.js` builds that without
 * touching the SDK at all, to keep the SDK behind this one file, per the
 * file docstring) turned into a real embed object. No title — a table
 * embed sits inline with a message's own text, not as its own titled
 * card, unlike `notice()`.
 */
function fieldsToEmbed(fields) {
  const builder = new InteractiveBuilder("");
  for (const f of fields) builder.addField(f.name, f.value, f.inline);
  const embed = builder.build();
  embed.color = DEFAULT_COLOR;
  return embed;
}

/**
 * Merges `toMezonContent`'s `tables` (if any) into `content.embed` as
 * real embed objects, and drops the `tables` key — `markdown.js` itself
 * never touches the SDK (see its file docstring), so it hands back plain
 * field data and this is where that becomes something `channel.send`
 * actually understands. A message with no table passes through
 * unchanged; `content.embed` is genuinely tables-turned-embeds, distinct
 * from — and additive with — any `mk` styling already on `content.t`,
 * per Mezon accepting both on one message the same way `notice()`'s own
 * `{t, embed}` output already does.
 */
function withTableEmbeds(content) {
  const { tables, ...rest } = content;
  if (!tables || !tables.length) return rest;
  return { ...rest, embed: tables.map((table) => fieldsToEmbed(table.fields)) };
}

/**
 * How an attention level looks in chat.
 *
 * Colour and icon carry the level because the Gate's whole job is
 * deciding how much of the user's attention something deserves, and a DM
 * that renders every nudge identically throws that judgement away at the
 * last step. SILENT has no entry: it never reaches a channel by
 * definition, and giving it a style would imply it could.
 */
const LEVEL_STYLE = {
  inform: { color: "#5b8def", icon: "ℹ️" },
  recommend: { color: "#f0a020", icon: "💡" },
  ask: { color: "#f2683c", icon: "❓" },
  act: { color: "#e5484d", icon: "🚨" },
};

/**
 * Flatten a notification's `content` blocks into description text.
 *
 * The digest reasons (`day.plan`, `day.review`, `task.at_risk`,
 * `task.blocked_cascade`) carry their itemised detail as one text block
 * per line, because the web renderer wraps each block in its own element.
 * Chat has no such structure, so the lines are rejoined here — without
 * this a DM shows "3 việc đến hạn hôm nay" and names none of them.
 *
 * The first block repeats `body` by design (the backend composes body as
 * the summary line and puts it at the head of `content`), so it is dropped
 * rather than printed twice. Non-text blocks are skipped: an image or a
 * code fence has no sensible plain-chat rendering, and guessing one is
 * worse than leaving it to the in-app card.
 */
function contentLines(content, body) {
  if (!Array.isArray(content)) return [];
  return content
    .filter((block) => block && block.type === "text" && typeof block.text === "string")
    .map((block) => block.text)
    .filter((text) => text.trim() && text !== body);
}

/**
 * Render a notification pushed from Cortex, with the buttons that make it
 * worth interrupting someone for.
 *
 * A nudge nobody can answer is a one-way announcement, and the reason this
 * bot exists is that the Attention Gate already has levels (`ASK`, `ACT`)
 * that presuppose a reply and had nowhere to be answered. So: a task the
 * notification is *about* gets ✅ Xong and ⏰ Dời sang mai.
 *
 * **Không có nút tắt nhắc.** Nó từng ở đây và đã bị gỡ: đặt "đừng nói nữa"
 * cạnh "xong" là để hai thao tác rất khác nhau cách nhau một lần bấm nhầm,
 * trên một thẻ đọc lướt lúc đang bận — và cái giá của lần nhầm đó là một
 * loại nhắc tắt vĩnh viễn mà người dùng không biết mình đã tắt. Tắt nhắc
 * vẫn làm được, chỉ là phải nói ra: `*mute` trong DM, hoặc Cortex →
 * Settings. `reason_key` vẫn in trong thân thẻ, nên nó vẫn là một tra cứu
 * chứ không phải một cuộc tìm kiếm.
 *
 * Everything these buttons need is in their ids (see `actions.js`): a DM
 * sits in a chat list for days and will be clicked long after the process
 * that sent it restarted. Nothing here is looked up in memory.
 *
 * `payload.task_id` is what the backend already puts on every task-shaped
 * reason (`notification_subscribers.py`). Các digest không có một chủ thể
 * duy nhất nên không có hai nút đó; riêng `day.review` có thẻ của chính nó
 * (`reviewCard.js`) vì cuối ngày là lúc người ta muốn *chốt sổ*, không
 * phải lúc đọc thêm một danh sách. `actions` stays unrendered: every entry in it today is a
 * `navigate` to a web route, which in a DM is a link to somewhere the
 * person deliberately isn't.
 *
 * `reason_key` also stays in the body, not just on a button, because it is
 * the exact string `*mute task.overdue` takes and Settings lists — naming
 * it turns "stop telling me this" from a search into a lookup.
 */
function notification({
  title,
  body,
  content,
  attention_level: level,
  reason_key: reasonKey,
  payload,
  notification_id: notificationId,
}) {
  if (reasonKey === "day.review") {
    // Yêu cầu lười: `reviewCard` require ngược `embed` để dùng FormBuilder,
    // nên import ở đầu tệp sẽ là một vòng tròn.
    const { renderDayReview } = require("./reviewCard");
    return renderDayReview({ title, body, payload, notificationId });
  }

  const style = LEVEL_STYLE[level] ?? LEVEL_STYLE.inform;
  const form = new FormBuilder(`${style.icon} ${title}`);
  const description = [body, ...contentLines(content, body)].filter(Boolean).join("\n");
  if (description) form.description(description);
  form.color = style.color;
  if (reasonKey) {
    form.field("Loại nhắc", `\`${reasonKey}\` — tắt được trong Cortex → Settings`);
  }

  const taskId = payload?.task_id;
  if (taskId) {
    form.button(actionId("notif_task_done", taskId), "✅ Xong", STYLE.SUCCESS);
    form.button(actionId("notif_task_snooze", taskId), "⏰ Dời sang mai", STYLE.SECONDARY);
  }
  return form.build();
}

/** A notice with no form: title, body, optional key/value lines. */
function notice(title, body, { fields = [], color } = {}) {
  const form = new FormBuilder(title);
  if (body) form.description(body);
  for (const f of fields) form.field(f.name, f.value, f.inline ?? false);
  if (color) form.color = color;
  return form.build();
}

module.exports = {
  FormBuilder,
  STYLE,
  text,
  notice,
  notification,
  contentLines,
  LEVEL_STYLE,
  DEFAULT_COLOR,
  fieldsToEmbed,
  withTableEmbeds,
};
