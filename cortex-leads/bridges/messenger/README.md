# Messenger bridge

Meta webhook -> Cortex Event Format v1 -> HMAC-signed `POST /ingest/v1/events` (chiều vào), and
Cortex Action Format v1 `POST /actions` -> Graph Send API (chiều ra). The bridge is one of the two
blocking layers (DESIGN §5.2, N3): it refuses what the platform forbids.

    python -m bridges.messenger.app        # listens on :8110 (MESSENGER_PORT)

## Env
| Var | Meaning |
|---|---|
| `MESSENGER_APP_SECRET` | Meta app secret; signs webhook bodies (`X-Hub-Signature-256`) |
| `MESSENGER_VERIFY_TOKEN` | any string you also type into the Meta dashboard (GET challenge) |
| `MESSENGER_PAGE_TOKEN` | Page access token. Or put it in `data/messenger_page_token` (gitignored). Sent as `Authorization: Bearer`, never in a URL, never logged |
| `MESSENGER_PAGE_ID` | fallback Page id when an entry has no `id` |
| `MESSENGER_OWN_APP_ID` | Meta app id of this integration (echoes with this id are `bot`) |
| `MESSENGER_HUMAN_APP_IDS` / `MESSENGER_BOT_APP_IDS` | optional comma lists of echo app_ids that are people-typing tools / known bots (see rules) |
| `CL_INGEST_URL` | e.g. `http://localhost:8000/ingest/v1/events` |
| `CL_CONNECTOR_ID` / `CL_CONNECTOR_SECRET` | the connector; same secret signs ingest and verifies `/actions` |
| `MESSENGER_GRAPH_VERSION` | default `v25.0` |
| `MESSENGER_POLICY` | inline JSON, e.g. `{"ai_send":true,"quiet_hours":[21,7],"max_per_minute":20}`. `ai_send` defaults to **false**; `quiet_hours` = `[start,end)` hour in Asia/Ho_Chi_Minh, applies to `ai:*` only; `max_per_minute` default 30 |

Missing required variable -> the app refuses to start. No defaults for secrets.
State: `data/messenger_actions.json` (action_id -> result, the idempotency store).

## Register on Meta (dev mode)
1. developers.facebook.com -> create an app (type Business), add the **Messenger** product.
2. Messenger -> API setup: connect the Page, generate the Page token (-> `MESSENGER_PAGE_TOKEN`).
3. Keep the app in **Development mode**: only roles Admin/Developer/**Tester** of the app can message the Page and be answered. Add testers under App roles; each must accept the invite. No App Review is needed for this.
4. Webhooks -> Callback URL `https://<tunnel>/webhook`, Verify token = `MESSENGER_VERIFY_TOKEN`; subscribe the Page to `messages` and **`message_echoes`** (without echoes staff/bot replies are invisible and every conversation looks silent).
5. Copy app secret (Settings -> Basic) to `MESSENGER_APP_SECRET`, app id to `MESSENGER_OWN_APP_ID`.

## cloudflared
    cloudflared tunnel --url http://localhost:8110     # prints https://<random>.trycloudflare.com
Use `https://<random>.trycloudflare.com/webhook` as callback URL (quick tunnels change on restart; use a
named tunnel for anything lasting). Expose only `/webhook`; point the connector's `outbound.url` at
`http://<bridge-host>:8110/actions` on a private network, not through the public tunnel if you can avoid it.

## `sender.role` rules (R13, R26)
For a `messaging[]` item with `message`, first match wins:
1. not `is_echo` (sender.id = customer PSID) -> `customer`
2. echo, no `app_id` (a person in the Page inbox / Business Suite) -> `staff`
3. echo, `app_id == MESSENGER_OWN_APP_ID` (Cortex) -> `bot`
4. echo, `app_id` in `MESSENGER_HUMAN_APP_IDS` (comma list: Pancake inbox, Business Suite...) -> `staff`
5. echo, `app_id` in `MESSENGER_BOT_APP_IDS` (known bots, e.g. Botcake) -> `bot`
6. echo, any other `app_id` -> **`staff`**, `meta.echo_app="unknown:<id>"`, one warning log per app_id
`staff.external_id` stays empty: Meta does not say which staff member.
Why: `sender.role` drives the silence clock. Most SMEs answer through a third-party inbox (Pancake...), whose
echoes carry that tool's app_id. Taking a bot for staff only misses one lead; taking a person for a bot never
resets the clock and ruins the H1 measurement. So unknown means staff, and bots must be declared explicitly.
Finding Pancake's app_id: start the bridge, reply once from Pancake to a test conversation, read the warning
`echo from unknown app_id <id> treated as staff` (or `meta.echo_app="unknown:<id>"` on the stored message), then
put the id in `MESSENGER_HUMAN_APP_IDS` and restart. Do the same for each bot you find replying.
In an echo the Page is `sender.id` and the customer is `recipient.id`; the conversation key is always the customer PSID.
Other fields: `external_id = messenger:<page_id>:<mid>`, `occurred_at` = `timestamp` ms -> UTC,
attachments -> `{type,url}`. delivery/read/postback/empty events are skipped.

## Chiều ra: order of checks
`type != send_message` or `channel.kind != messenger` -> `NOT_SUPPORTED`; actor `ai:*` and `ai_send=false` ->
`AI_SEND_DISABLED`; `window.open=false` -> `WINDOW_CLOSED`; `window.basis=human_agent` and actor not `staff:*` ->
`PLATFORM_POLICY`; `ai:*` inside quiet hours -> `QUIET_HOURS`; over `max_per_minute` -> `RATE_LIMIT` (not remembered).
Send: free window -> `messaging_type=RESPONSE`; `human_agent` + `staff:*` -> `MESSAGE_TAG` + `tag=HUMAN_AGENT`.
Text = `text` + `"\n— " + disclosure`. Graph 5xx/429/network -> `error retryable=true`; other 4xx -> `retryable=false`
(errors are not stored, so the core's retry with the same `action_id` is allowed). `sent`/`refused` are
stored by `action_id` and replayed without calling Meta.
Webhook: 200 immediately, events go to an in-memory queue, flushed with backoff (0.5s doubling, max 30s);
a restart loses queued events, but Meta re-delivers unacknowledged ones and ingest dedupes by `external_id`.

## Source and unverified assumptions
Fetched 2026-10-12 from developers.facebook.com `messenger-platform/webhooks` and `/send-messages`.
Confirmed there: `object="page"`, `entry[].id`, `entry[].messaging[]`, `sender.id`, `recipient.id`, `timestamp`,
`message.mid/text/attachments[].type/payload.url`, `X-Hub-Signature-256: sha256=<HMAC-SHA256(app secret, raw body)>`,
GET `hub.mode=subscribe` / `hub.verify_token` / `hub.challenge` (403 on mismatch), Send body `recipient.id`,
`messaging_type`, `message.text`, Human Agent = 7 days, human reply, no promotional content.
**Not confirmed by those pages (assumptions):**
- `message.is_echo` and `message.app_id`: not on these pages; field names taken from the echoes reference as remembered. **In particular, that a message typed in the Page inbox arrives with no `app_id`** (rule 3) must be checked on a real Page before trusting H1 numbers.
- Literal enum strings `MESSAGE_TAG` and `HUMAN_AGENT` (page names them in prose only).
- Signature is checked over the raw received bytes (the docs say Meta signs the escaped-Unicode payload, which is what arrives on the wire).
- Send endpoint `POST /{version}/me/messages` (page shows both `me` and `{PAGE-ID}`).
- Whether the HUMAN_AGENT tag is valid for a draft that a staff member sends by pressing a button (DESIGN open question, §10).
