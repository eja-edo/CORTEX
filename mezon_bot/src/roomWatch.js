"use strict";

/**
 * The business logic behind "a meeting ended → ask which project → when the
 * summary is ready, DM it and create today's tasks."
 *
 * Two stages of state, on purpose kept apart:
 *
 * - Stage 1 (which project?) lives in the shared `pendingForms` — a normal
 *   pick-and-submit card, same as `*switch_model`. It only has to survive
 *   the few minutes between the DM landing and someone answering it.
 * - Stage 2 (who answered, with what) lives in `this.waiters`, a map of its
 *   own. It has to survive from the moment someone picks a project to the
 *   moment orchestrator finishes summarising — which can be much longer
 *   than `pendingForms`' 30-minute TTL, and must not be evicted by an
 *   unrelated `*switch_model`/`*new` card competing for that map's 200-entry
 *   cap. Both maps are in-memory and lost on restart, a trade-off accepted
 *   for the same reason `pendingForms.js` already accepts it: no schema, no
 *   migration, no cleanup job for state this short-lived. What's lost on a
 *   restart mid-meeting is a summary DM, not anything the backend owns —
 *   the meeting, the room, and the eventual summary all live in
 *   orchestrator's own Postgres regardless of whether this bot was up to
 *   catch the notification.
 */

const { logger } = require("./logger");
const { isoDate, DEFAULT_TIMEZONE } = require("./mezon/clock");
const {
  renderProjectPicker,
  renderMeetingSummary,
  renderTasksCreatedFromSummary,
} = require("./mezon/roomWatchCards");

/** A `participants` entry can be a bare identity string (confirmed shape,
 *  Summary API example) or — per Rooms API's redacted example — an object.
 *  Accepts either; logs instead of guessing when it's neither, so a real
 *  mismatch is visible rather than silently dropping people from the
 *  notification. */
function participantIdentity(entry) {
  if (typeof entry === "string" || typeof entry === "number") return String(entry);
  if (entry && typeof entry === "object") {
    const id = entry.participant_identity ?? entry.identity ?? entry.id;
    if (id !== undefined && id !== null) return String(id);
  }
  return null;
}

const ROOM_FETCH_RETRY_DELAY_MS = 1000;

/** One retry after a short delay for a fetch whose failure would otherwise
 *  take down notifications for every participant/waiter of a room at once —
 *  a single transient blip (Cortex briefly down) shouldn't cost the whole
 *  room its project picker or its summary. A second failure still
 *  propagates, same as before this existed. */
async function withOneRetry(fn) {
  try {
    return await fn();
  } catch (err) {
    await new Promise((resolve) => setTimeout(resolve, ROOM_FETCH_RETRY_DELAY_MS));
    return fn();
  }
}

class RoomWatchService {
  constructor({ gateway, cortex, orchestrator, pendingForms, timezone = DEFAULT_TIMEZONE }) {
    this.gateway = gateway;
    this.cortex = cortex;
    this.orchestrator = orchestrator;
    this.pendingForms = pendingForms;
    this.timezone = timezone;
    // room_id -> [{ mezonUserId, cortexUserId, projectId, roomName }]
    this.waiters = new Map();
  }

  start() {
    this.orchestrator.streamMetadata({
      onEvent: (event) => this._onMetadataEvent(event),
    });
  }

  stop() {
    this.orchestrator.stop();
  }

  _onMetadataEvent(event) {
    const type = event?.event_type;
    if (type === "room_ended") {
      this.handleRoomEnded(event).catch((err) => {
        logger.error("handleRoomEnded failed", { error: err?.message, room_id: event?.room_id });
      });
    } else if (type === "room_summary_done") {
      this.handleSummaryDone(event).catch((err) => {
        logger.error("handleSummaryDone failed", { error: err?.message, room_id: event?.room_id });
      });
    }
  }

  /**
   * Room ended → DM every linked participant a project picker.
   *
   * Every participant is treated as wanting the summary — there is no
   * opt-in command for this yet — so the only filter is "does this Mezon
   * account resolve to a Cortex user at all." One participant's failure
   * (unlinked, Cortex briefly down, an odd `participants` entry) must not
   * stop the others from getting their card.
   */
  async handleRoomEnded({ room_id: roomId, room_name: roomName }) {
    if (!roomId) return;

    let room;
    try {
      room = await withOneRetry(() => this.orchestrator.getRoomById(roomId));
    } catch (err) {
      // A retry already ran inside withOneRetry — this is a persistent
      // failure, not a blip. Nothing to fall back to without the
      // participant list, but log it distinctly from a per-participant
      // send failure below: this one cost every participant their card.
      logger.error("could not fetch room after retry; no participant will get a project picker", {
        room_id: roomId,
        error: err?.message,
      });
      return;
    }
    const rawParticipants = room?.participants ?? [];
    const identities = rawParticipants
      .map((entry) => {
        const id = participantIdentity(entry);
        if (!id) {
          logger.warn("room_ended participant entry did not match any known shape", {
            room_id: roomId,
            entry,
          });
        }
        return id;
      })
      .filter(Boolean);

    for (const mezonUserId of identities) {
      try {
        await this._sendProjectPicker({ mezonUserId, roomId, roomName });
      } catch (err) {
        logger.warn("could not send project picker to participant", {
          room_id: roomId,
          mezon_user_id: mezonUserId,
          error: err?.message,
        });
      }
    }
  }

  async _sendProjectPicker({ mezonUserId, roomId, roomName }) {
    const identity = await this.cortex.resolveChannel(mezonUserId);
    if (!identity?.linked) return; // no Cortex account to attach a task to

    const projects = await this.cortex.listProjects(identity.user_id);
    const formId = this.pendingForms.put({
      kind: "project_pick",
      roomId,
      roomName,
      projects,
    });
    await this.gateway.sendDirectMessage(mezonUserId, renderProjectPicker(projects, roomName, formId));
  }

  /** Called from `router.js#_handleProjectPick` once someone answers the
   *  picker — the only writer of `this.waiters`. */
  recordProjectPick({ roomId, roomName, mezonUserId, cortexUserId, projectId }) {
    const list = this.waiters.get(roomId) ?? [];
    list.push({ mezonUserId, cortexUserId, projectId, roomName });
    this.waiters.set(roomId, list);
  }

  /**
   * Summary ready → DM it to every waiter for this room and create their
   * action items as tasks due today.
   *
   * If nobody picked a project for this room (or `waiters` never saw it —
   * every participant was unlinked, say), there is nothing to do: this is
   * the normal case for most rooms, not an error.
   */
  async handleSummaryDone({ room_id: roomId, room_name: roomName }) {
    const waiters = this.waiters.get(roomId);
    if (!waiters?.length) return;

    let summary;
    try {
      summary = await withOneRetry(() => this.orchestrator.getSummaryByRoomId(roomId));
    } catch (err) {
      // Same reasoning as handleRoomEnded: a persistent fetch failure here
      // would otherwise cost every waiter their summary. Keep the waiters —
      // a resend of room_summary_done, if orchestrator ever does one, should
      // still find them.
      logger.error("could not fetch summary after retry; keeping waiters for a possible resend", {
        room_id: roomId,
        error: err?.message,
      });
      return;
    }
    const summaryData = summary?.summary_data;
    if (!summaryData || !("action_items" in summaryData)) {
      // Per docs/API_REFERENCE.md §6: an outbox retry after an LLM failure
      // leaves `summary_data` as `{}` until it succeeds. Keep the waiters —
      // if orchestrator ever re-pushes `room_summary_done` for this room,
      // this same lookup should find them again.
      logger.info("room_summary_done arrived but summary_data isn't ready yet", { room_id: roomId });
      return;
    }

    const today = isoDate(new Date(), this.timezone);
    const actionItems = summaryData.action_items ?? {};
    const generalItems = actionItems.general ?? [];

    const failedWaiters = [];
    for (const waiter of waiters) {
      try {
        await this._deliverSummaryToWaiter({ waiter, roomName, summaryData, actionItems, generalItems, today });
      } catch (err) {
        logger.warn("could not deliver meeting summary to a waiter", {
          room_id: roomId,
          mezon_user_id: waiter.mezonUserId,
          error: err?.message,
        });
        failedWaiters.push(waiter);
      }
    }

    // Only drop waiters we actually delivered to. A waiter whose send/task
    // creation failed (transient Mezon/Cortex error, not "not ready yet")
    // stays queued — otherwise their summary is lost with no way to retry
    // even if this same room_summary_done event were ever resent.
    if (failedWaiters.length) {
      this.waiters.set(roomId, failedWaiters);
      logger.warn("some waiters did not receive the meeting summary; keeping them queued", {
        room_id: roomId,
        failed_count: failedWaiters.length,
      });
    } else {
      this.waiters.delete(roomId);
    }
  }

  async _deliverSummaryToWaiter({ waiter, roomName, summaryData, actionItems, generalItems, today }) {
    await this.gateway.sendDirectMessage(waiter.mezonUserId, renderMeetingSummary(roomName, summaryData));

    const ownItems = actionItems[waiter.mezonUserId] ?? [];
    const items = [...ownItems, ...generalItems];
    const created = [];
    for (const title of items) {
      try {
        await this.cortex.createTask(
          {
            title,
            due_date: `${today}T00:00:00Z`,
            ...(waiter.projectId ? { project_id: waiter.projectId } : {}),
          },
          waiter.cortexUserId
        );
        created.push(title);
      } catch (err) {
        logger.warn("could not create task from meeting action item", {
          mezon_user_id: waiter.mezonUserId,
          title,
          error: err?.message,
        });
      }
    }

    await this.gateway.sendDirectMessage(waiter.mezonUserId, renderTasksCreatedFromSummary(created));
  }
}

module.exports = { RoomWatchService, participantIdentity };
