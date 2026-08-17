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

/** A notice with no form: title, body, optional key/value lines. */
function notice(title, body, { fields = [], color } = {}) {
  const form = new FormBuilder(title);
  if (body) form.description(body);
  for (const f of fields) form.field(f.name, f.value, f.inline ?? false);
  if (color) form.color = color;
  return form.build();
}

module.exports = { FormBuilder, STYLE, text, notice, DEFAULT_COLOR };
