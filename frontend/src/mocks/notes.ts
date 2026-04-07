import type { NoteItem } from '../components/NoteSidebar'

const MOCK_NOTES: NoteItem[] = [
  {
    id: 'note-1',
    date: '4/6/2026',
    contentMd:
      '# Bắt đầu đi xin dấu thực tập\n- Thực tập hệ thống thông tin quản lý\n- Thực tập hệ thống thông tin tích hợp\n- Thực tập quản trị dự án phần mềm\nhttps://docs.google.com/document/d/1P9ldp5hSor13MthUFvPvk2hVU2i9IFVQ/edit',
  },
  {
    id: 'note-2',
    date: '4/6/2026',
    contentMd:
      '## day 4/6/2026\n- Todo\n- Lưu tất cả participant trong room\nAdd tất cả participant vào room data phục vụ sync.',
  },
  {
    id: 'note-3',
    date: '4/3/2026',
    contentMd:
      '# Release 2026040x\nChecklist triển khai bản phát hành và các hạng mục cần rà soát.',
  },
]

export async function fetchMockNotes(): Promise<NoteItem[]> {
  await new Promise((resolve) => setTimeout(resolve, 160))
  return MOCK_NOTES.map((note) => ({ ...note }))
}
