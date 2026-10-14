# Pancake bridge

Poll Pancake (GET only) -> Cortex Event Format v1 -> HMAC-signed `POST /ingest/v1/events`.

    PANCAKE_PAGE_ID=... PANCAKE_PAGE_TOKEN=... CL_INGEST_URL=http://localhost:8010/ingest/v1/events \
    CL_CONNECTOR_ID=conn_... CL_CONNECTOR_SECRET=... python -m bridges.pancake.run [--loop 60]

The token may instead sit in `data/pancake_page_token` (gitignored). It has full page rights and is
passed as a query parameter by Pancake's design: URLs are never logged, httpx logging is capped at
WARNING. Cursor: `data/pancake_cursor.json` (per page, epoch seconds; first run backfills 7 days).
The cursor only moves after the ingest API accepted every batch; the boundary second may be re-sent
and comes back as `duplicate`.

## `sender.role` rules (first match wins)
1. `from.is_automated` or `from.ai_generated` -> `bot`
2. `from.admin_id` or `from.uid` -> `staff` (`staff.external_id` = admin_id, else uid)
3. `from.id == page_id` with no admin info -> `bot` (cannot prove a human wrote it; mislabelling it
   `staff` would reset the silence clock and hide a dropped lead)
4. otherwise `customer`

## Source and unverified assumptions
Field names are from https://developer.pancake.biz/openapi/openapi.yaml (fetched 2026-10-10):
`GET /public_api/v2/pages/{id}/conversations` (`since`, `order_by=updated_at`, `type=INBOX`,
`last_conversation_id`), `GET /public_api/v1/pages/{id}/conversations/{cid}/messages`
(`current_count`; newest first, 30 per call), `Message.from.{id,admin_id,uid,is_automated,ai_generated}`,
datetimes are UTC without offset. Not verified against a live page:
- whether messages typed by staff in the Facebook app (not Pancake) carry `admin_id`; they would map to `bot` (rule 3);
- that `conv_from` is always the customer for inbox threads;
- text is taken from `original_message`; `message` may contain HTML.
Only INBOX threads are read; comments are ignored in v0. Do not call Pancake for real before
the connector's contract test is signed off.
