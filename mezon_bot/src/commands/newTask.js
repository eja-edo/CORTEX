"use strict";

/**
 * `*new <tiêu đề>` — create a task.
 *
 * Named `new` rather than `task` because `*tasks` already owns the plural
 * and a one-letter difference between "list my work" and "create work" is
 * a mistake waiting to happen on a phone keyboard.
 *
 * The argument pre-fills the title instead of creating immediately: a
 * task created from a single line of chat, with no chance to add a date,
 * is the kind of half-entry that turns a task list into noise. The form
 * costs one extra tap and makes the due date reachable.
 */

const { renderTaskForm } = require("../mezon/taskCards");

const newTaskCommand = {
  name: "new",
  aliases: ["nt"],
  description: "Tạo việc mới",
  usage: "*new <tiêu đề>",
  requiresLink: true,

  async run({ args, pendingForms, reply }) {
    const formId = pendingForms.put({ kind: "task_create" });
    await reply(renderTaskForm(args.trim(), formId));
  },
};

module.exports = { newTaskCommand };
