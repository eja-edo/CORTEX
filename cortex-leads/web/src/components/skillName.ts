/** What a person calls a skill. The skill's own name (`tra-loi-khach`) is a key in its file and cannot change without making a new version
 * that has to be tried again, so the readable name lives here. A custom skill made from the form keeps the short name its owner typed. */
const TITLES: Record<string, string> = {
  'tra-loi-khach': 'Trả lời khách',
  'hoi-lai-khach-im': 'Hỏi lại khách im lặng',
  'hoi-lai-dung-hen': 'Nhắc khách đúng hẹn',
  'thu-nhanh': 'Thử nhanh (chỉ để thử)',
  'tom-tat-buoi-hoc': 'Tổng kết buổi học',
  'cham-bai': 'Chấm bài',
  'soan-bai-tap': 'Soạn bài tập',
}
const CUSTOM = 'tuy-chinh-'

export const skillTitle = (name: string) => TITLES[name] ?? (name.startsWith(CUSTOM) ? `Kỹ năng riêng: ${name.slice(CUSTOM.length)}` : name)
