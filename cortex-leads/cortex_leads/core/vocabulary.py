"""Structural vocabulary only. Business words (intents, reason codes, fact kinds, roles) live in
the sandbox's domain pack (DESIGN A6)."""
EVENT_TYPES = {
    "customer.message",
    "staff.reply",
    "conversation.silent",
    "conversation.awaiting_reply",  # WP16: customer finished a turn nobody answered
    "conversation.promised_date_reached",
    "conversation.outcome",
    "deal.updated",
    "draft.expired",
}
# DESIGN A9: `send_to_customer` is only valid for a skill whose send_policy allows auto (loader lint).
OUTPUT_KINDS = {"draft_for_staff", "send_to_customer", "staff_task", "owner_digest", "none"}
# Fact kinds every domain has; a pack adds its own via `fact_kinds`.
CORE_FACT_KINDS = {"promised_date", "outcome", "offchannel"}
