"use strict";

/**
 * `*tasks` — list open work and close one, in a single card.
 *
 * `*tasks` with no argument lists everything still open; `*tasks today`
 * narrows to what is due by today, which is the filter people actually
 * want on a phone. Both are the same `GET /tasks` query with different
 * parameters — the bot picks parameters, never criteria.
 *
 * "Open" means `status=todo`. Not a guess: `pending_confirm` tasks are
 * extractor proposals that haven't been accepted (see
 * `TodayNeedsConfirmationItem`'s docstring on why those must not be shown
 * as real work), and `in_progress` is a state the bot has no way to
 * change, so offering to complete one from here would be the only path to
 * an illegal transition the service would reject anyway.
 */

const { renderTaskList, renderNoTasks } = require("../mezon/taskCards");

/** `YYYY-MM-DD` for today, UTC — the same clock `today.py` ranks by. */
function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

const tasksCommand = {
  name: "tasks",
  aliases: ["task"],
  description: "Xem việc đang mở, đánh dấu xong (`*tasks today` để lọc)",
  usage: "*tasks [today]",
  requiresLink: true,

  async run({ cortex, identity, args, pendingForms, reply }) {
    const wantsToday = args.trim().toLowerCase() === "today";
    const tasks = await cortex.listTasks(identity.userId, {
      status: "todo",
      due_before: wantsToday ? todayIso() : undefined,
    });

    if (!Array.isArray(tasks) || tasks.length === 0) {
      await reply(renderNoTasks());
      return;
    }

    const formId = pendingForms.put({ tasks });
    await reply(
      renderTaskList(tasks, formId, {
        heading: wantsToday ? `${tasks.length} việc đến hạn hôm nay` : `${tasks.length} việc đang mở`,
      })
    );
  },
};

module.exports = { tasksCommand };
