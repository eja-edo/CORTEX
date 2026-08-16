export function WebhookTriggerConfig() {
  return (
    <div className="wf-config-fields">
      <div className="wf-config-field">
        <p style={{ color: 'var(--text-secondary)', fontSize: '13px', margin: 0 }}>
          Không cần cấu hình — URL webhook và secret được tự động sinh ra khi bạn lưu và kích hoạt workflow.
        </p>
        <span className="wf-config-hint">
          Secret chỉ hiển thị một lần ngay sau khi tạo — hãy lưu lại lúc đó.
        </span>
      </div>
    </div>
  )
}
