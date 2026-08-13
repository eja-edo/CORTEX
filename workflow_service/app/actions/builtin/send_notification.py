from app.actions.builtin.request_attention import RequestAttentionAction


class SendNotificationAction(RequestAttentionAction):
    """Deprecated alias for `action.request_attention` (Milestone 4.3 M2).
    Kept so workflow definitions created before this action was renamed keep
    working — `action_type` stays `action.send_notification`, but `execute()`
    (inherited) now goes through the same Attention Gate path instead of
    posting straight into the notifications table."""

    @property
    def action_type(self) -> str:
        return "action.send_notification"

    @property
    def display_name(self) -> str:
        return "Gửi Notification (deprecated — dùng \"Yêu Cầu Chú Ý\")"
