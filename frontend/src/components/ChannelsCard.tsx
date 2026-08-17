import { useState } from 'react'
import { Check, Copy, Link2, Trash2 } from 'lucide-react'
import type { AttentionLevel, ChannelLinkCode, UserChannel } from '../types'

/**
 * Linking and managing the ways Cortex can reach you outside the browser.
 *
 * The direction of the linking flow is a security property, not a UX
 * choice: the code is minted here, where the session is already
 * authenticated, and typed into the chat app. Doing it the other way —
 * typing a Mezon id into this page — would let anyone claim anyone else's
 * chat account, because those ids are visible to every member of a clan.
 * The copy below says so, so the flow does not look like pointless
 * ceremony to whoever maintains it next.
 *
 * Boundary #2 from docs/planning-v3.md applies: this card is a place to
 * turn things *off*. A user who never opens it still gets notifications
 * in-app, and a channel they link starts working immediately at the
 * adapter's default floor.
 */

type ChannelsCardProps = {
   channels: UserChannel[]
   onCreateLinkCode: (channel: string) => Promise<ChannelLinkCode>
   onUpdateChannel: (
      channelId: string,
      updates: { enabled?: boolean; min_level?: string }
   ) => Promise<void>
   onDeleteChannel: (channelId: string) => Promise<void>
   formatDateTimeVi: (isoDateTime: string | null) => string
}

const CHANNEL_LABELS: Record<string, string> = {
   mezon: 'Mezon',
   telegram: 'Telegram',
   slack: 'Slack',
   email: 'Email',
   push: 'Trình duyệt',
   webhook: 'Webhook',
   in_app: 'Trong ứng dụng',
}

// Ordered loudest-last so the select reads as a volume dial. SILENT is
// absent on purpose: a channel nobody can reach is what the enable toggle
// and the delete button are for, and offering it twice invites the
// question of which one wins.
const LEVEL_OPTIONS: { value: AttentionLevel; label: string }[] = [
   { value: 'inform', label: 'Mọi thứ' },
   { value: 'recommend', label: 'Đáng chú ý trở lên' },
   { value: 'ask', label: 'Chỉ việc cần quyết định' },
   { value: 'act', label: 'Chỉ việc khẩn cấp' },
]

function formatCountdown(seconds: number): string {
   const minutes = Math.floor(seconds / 60)
   const rest = seconds % 60
   return `${minutes}:${String(rest).padStart(2, '0')}`
}

export function ChannelsCard({
   channels,
   onCreateLinkCode,
   onUpdateChannel,
   onDeleteChannel,
   formatDateTimeVi,
}: ChannelsCardProps) {
   const [linkCode, setLinkCode] = useState<ChannelLinkCode | null>(null)
   const [secondsLeft, setSecondsLeft] = useState(0)
   const [busy, setBusy] = useState(false)
   const [error, setError] = useState<string | null>(null)
   const [copied, setCopied] = useState(false)

   const handleCreateCode = async () => {
      setBusy(true)
      setError(null)
      setCopied(false)
      try {
         const created = await onCreateLinkCode('mezon')
         setLinkCode(created)
         setSecondsLeft(created.expires_in)

         // A visible countdown rather than a silent expiry. The backend
         // refuses an expired code with a deliberately vague message (it
         // will not say whether a code ever existed), so without a timer
         // here the user's only feedback would be "invalid" with no clue
         // that time was the reason.
         const startedAt = Date.now()
         const timer = setInterval(() => {
            const remaining = created.expires_in - Math.floor((Date.now() - startedAt) / 1000)
            if (remaining <= 0) {
               clearInterval(timer)
               setSecondsLeft(0)
               setLinkCode(null)
               return
            }
            setSecondsLeft(remaining)
         }, 1000)
      } catch (err) {
         setError(err instanceof Error ? err.message : 'Không tạo được mã liên kết')
      } finally {
         setBusy(false)
      }
   }

   const handleCopy = async () => {
      if (!linkCode) return
      try {
         await navigator.clipboard.writeText(linkCode.instruction)
         setCopied(true)
         setTimeout(() => setCopied(false), 2000)
      } catch {
         // Clipboard permission can be denied; the code is on screen
         // anyway, so this is not worth an error state.
      }
   }

   const linkableChannels = channels.filter((c) => c.channel !== 'in_app')

   return (
      <div className="settings-card">
         <div className="settings-card-title">Kênh nhận thông báo</div>
         <div className="settings-card-subtitle">
            Liên kết Mezon để Cortex nhắn được cho bạn khi đã đóng trình duyệt. Thông báo
            trong ứng dụng luôn bật và không cần liên kết gì.
         </div>

         {linkableChannels.length > 0 && (
            <div className="settings-channel-list">
               {linkableChannels.map((channel) => (
                  <div key={channel.id} className="settings-channel-row">
                     <div className="settings-channel-info">
                        <span className="settings-channel-name">
                           {CHANNEL_LABELS[channel.channel] ?? channel.channel}
                           {channel.label ? ` — ${channel.label}` : ''}
                        </span>
                        <span className="settings-channel-meta">
                           {channel.address_hint}
                           {!channel.verified && ' · chưa xác minh'}
                           {channel.last_used_at
                              ? ` · lần gửi cuối ${formatDateTimeVi(channel.last_used_at)}`
                              : ' · chưa gửi lần nào'}
                        </span>
                     </div>

                     <select
                        className="settings-channel-level"
                        value={channel.min_level}
                        disabled={!channel.enabled}
                        onChange={(e) =>
                           void onUpdateChannel(channel.id, { min_level: e.target.value })
                        }
                     >
                        {LEVEL_OPTIONS.map((option) => (
                           <option key={option.value} value={option.value}>
                              {option.label}
                           </option>
                        ))}
                     </select>

                     <label className="settings-channel-toggle">
                        <input
                           type="checkbox"
                           className="settings-toggle"
                           checked={channel.enabled}
                           onChange={(e) =>
                              void onUpdateChannel(channel.id, { enabled: e.target.checked })
                           }
                        />
                     </label>

                     <button
                        type="button"
                        className="btn btn-ghost settings-channel-delete"
                        title="Gỡ liên kết"
                        onClick={() => void onDeleteChannel(channel.id)}
                     >
                        <Trash2 size={16} />
                     </button>
                  </div>
               ))}
            </div>
         )}

         {!linkCode ? (
            <div className="settings-actions-row">
               <button
                  type="button"
                  className="btn btn-primary"
                  disabled={busy}
                  onClick={() => void handleCreateCode()}
               >
                  <Link2 size={16} />
                  {linkableChannels.some((c) => c.channel === 'mezon')
                     ? 'Liên kết thêm tài khoản Mezon'
                     : 'Liên kết Mezon'}
               </button>
            </div>
         ) : (
            <div className="settings-link-code">
               <div className="settings-link-code-value">
                  <code>{linkCode.code}</code>
                  <button
                     type="button"
                     className="btn btn-ghost"
                     title="Sao chép lệnh"
                     onClick={() => void handleCopy()}
                  >
                     {copied ? <Check size={16} /> : <Copy size={16} />}
                  </button>
               </div>
               <ol className="settings-link-steps">
                  <li>Mở Mezon, nhắn tin trực tiếp cho bot Cortex.</li>
                  <li>
                     Gõ <code>{linkCode.instruction}</code>
                  </li>
               </ol>
               <div className="settings-link-code-expiry">
                  Mã hết hạn sau {formatCountdown(secondsLeft)}. Chỉ dùng được một lần.
               </div>
            </div>
         )}

         {error && <div className="settings-meta-error">{error}</div>}
      </div>
   )
}
