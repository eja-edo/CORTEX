# Phân tích & Thiết kế UI/UX Mới cho Cortex

## 1. Tổng quan kiến trúc

Vấn đề cốt lõi của frontend hiện tại là nó vẫn "nghĩ" theo user-centric trong khi backend đã chuyển sang workspace-centric. Cần một cuộc tái cấu trúc toàn diện, không chỉ dịch chuyển vài component.

---

## 2. Sidebar & Navigation — Thiết kế lại từ đầu

### Vấn đề hiện tại

`Home` nằm dưới `WorkspaceSwitcher`, tạo cảm giác Home thuộc về workspace. `SidebarSection` cho Notes và Records bị trộn lẫn với workspace switcher, không có ranh giới rõ ràng giữa global scope và workspace scope.

### Cấu trúc sidebar mới

```
┌─────────────────────────────────┐
│  [C] Cortex          [collapse] │  ← topbar / brand
├─────────────────────────────────┤
│                                 │
│  ⌂  Home                       │  ← GLOBAL scope (user-level)
│  🔔 Notifications               │
│  ⏱  Recent                     │
│                                 │
├─────────── WORKSPACES ──────────┤
│  [Personal ▾]  [owner badge]    │  ← workspace switcher
│                                 │
│  ──── IN THIS WORKSPACE ────   │
│  📅  Schedule                   │
│  📝  Notes              [+]    │
│    ├─ Note A                    │
│    └─ Note B                    │
│  🎬  Records            [+]    │
│    ├─ Recording 1               │
│    └─ Recording 2               │
│                                 │
├─────────────────────────────────┤
│  ⚙  Settings                   │  ← user-level settings
└─────────────────────────────────┘
```

Ranh giới được thiết lập bằng visual separator + label "IN THIS WORKSPACE". Global items (Home, Notifications, Recent) luôn hiển thị bất kể workspace nào đang active.

---

## 3. Routing Structure

```
/                          → GlobalHome (user dashboard)
/notifications             → Notifications
/settings                  → UserSettings

/w/:workspaceId            → WorkspaceDashboard (hoặc redirect tới /w/:id/notes)
/w/:workspaceId/notes      → NotesList
/w/:workspaceId/notes/:id  → NoteEditor
/w/:workspaceId/records    → RecordsList
/w/:workspaceId/records/:assetId/knowledge → KnowledgeView
/w/:workspaceId/schedule   → ScheduleView
```

Workspace ID nằm trong URL thay vì chỉ trong state — đây là thay đổi quan trọng nhất. Nó cho phép deep linking, browser history hoạt động đúng, và tránh stale state khi switch workspace.

---

## 4. Home Page — Global Dashboard

### Layout

```
┌──────────────────────────────────────────────────────┐
│  Good morning, Alice                    [Ask AI ✦]   │
├──────────────┬───────────────────────────────────────┤
│              │                                        │
│  UPCOMING    │  RECENT ACTIVITY                      │
│  ─────────   │  ────────────────                     │
│  Today       │  [Note] "Project brief" — 2h ago      │
│  • 9am Class │  [Rec]  "Sprint review" — yesterday   │
│  • 2pm Exam  │  [Note] "Meeting notes" — 2d ago      │
│              │                                        │
│  Tomorrow    │  QUICK ACTIONS                        │
│  • Deadline  │  ─────────────                        │
│              │  [+ Note]  [⏺ Record]  [+ Event]     │
│              │                                        │
│  WORKSPACES  │  YOUR NOTES                           │
│  ─────────── │  ─────────────                        │
│  Personal 3  │  (recent across all workspaces)       │
│  Team    12  │                                        │
└──────────────┴───────────────────────────────────────┘
```

Nội dung Home không thuộc workspace nào, nó aggregate từ tất cả workspace của user.

---

## 5. Workspace CRUD — Phân tích & Implementation

### Endpoints cần dùng (đã có trong backend)

```
POST   /workspaces              → create
GET    /workspaces              → list (đã dùng)
PATCH  /workspaces/:id          → rename
DELETE /workspaces/:id          → delete
POST   /workspaces/:id/members  → add member
PATCH  /workspaces/:id/members/:userId → change role
DELETE /workspaces/:id/members/:userId → remove
```

### WorkspaceSwitcher mới

```
┌─────────────────────────────┐
│  [≡] Personal Workspace  ▾  │  ← click để mở dropdown
└─────────────────────────────┘

Dropdown:
┌─────────────────────────────┐
│  Switch workspace           │
├─────────────────────────────┤
│  ✓ Personal         owner   │
│    Team Alpha       editor  │
├─────────────────────────────┤
│  + Create workspace         │
│  ⚙ Manage workspaces       │
└─────────────────────────────┘
```

Context menu (3-dot) trên mỗi workspace item:
- Rename (inline edit)
- Manage Members (modal)
- Delete (confirm dialog, disabled cho personal workspace)

### WorkspaceCreateModal

```typescript
// Component nhỏ gọn, không cần full-page
function WorkspaceCreateModal({ onClose, onCreated }) {
  // POST /workspaces
  // Sau khi tạo → navigate('/w/:newId')
}
```

---

## 6. Workspace Dashboard — Có hay không?

**Kết luận: CÓ, nhưng minimal.**

Lý do: khi user mở workspace, họ cần orientation ngay. Một trang trắng hoặc redirect thẳng vào Notes sẽ gây disorientation.

### Workspace Dashboard layout

```
┌──────────────────────────────────────────────────────┐
│  Personal Workspace                    [+ Invite]    │
├──────────────┬───────────────────────────────────────┤
│  NOTES (12)  │  RECENT RECORDS                      │
│  ──────────  │  ──────────────                      │
│  [card]      │  [card]  [card]  [card]              │
│  [card]      │                                       │
│              │  UPCOMING (this workspace)            │
│  MEMBERS     │  ─────────────────────               │
│  ──────────  │  • Tomorrow 9am — Class              │
│  Alice owner │  • Friday — Deadline                 │
│  Bob editor  │                                       │
└──────────────┴───────────────────────────────────────┘
```

Dashboard chỉ là landing page — nhẹ, không fetch nhiều data. User sẽ navigate vào Notes/Records/Schedule từ đây.

---

## 7. Component Breakdown

### Folder structure đề xuất

```
src/
├── components/
│   ├── layout/
│   │   ├── AppShell.tsx          ← topbar + sidebar + main area
│   │   ├── Sidebar.tsx           ← global sidebar wrapper
│   │   ├── SidebarGlobal.tsx     ← Home, Notifications, Recent
│   │   ├── SidebarWorkspace.tsx  ← notes tree, records, schedule
│   │   └── WorkspaceSwitcher.tsx ← dropdown + CRUD actions
│   │
│   ├── workspace/
│   │   ├── WorkspaceDashboard.tsx
│   │   ├── WorkspaceCreateModal.tsx
│   │   ├── WorkspaceDeleteDialog.tsx
│   │   └── WorkspaceMembersModal.tsx
│   │
│   ├── notes/
│   │   ├── NoteEditor.tsx        ← hiện tại WorkspaceNoteEditor
│   │   ├── NoteTree.tsx          ← sidebar note list + tree
│   │   └── NoteSearch.tsx
│   │
│   ├── records/
│   │   ├── RecordPanel.tsx
│   │   ├── RecordingsList.tsx
│   │   └── AssetKnowledgeView.tsx
│   │
│   ├── schedule/
│   │   ├── CalendarView.tsx
│   │   └── ScheduleForm.tsx
│   │
│   ├── home/
│   │   └── GlobalHome.tsx
│   │
│   └── shared/
│       ├── ConfirmDialog.tsx
│       ├── Modal.tsx
│       ├── ContextMenu.tsx
│       └── InlineEdit.tsx
│
├── hooks/
│   ├── useWorkspace.ts           ← CRUD + switch
│   ├── useNotes.ts
│   ├── useSchedules.ts
│   └── useApi.ts                 ← requestWithAuth wrapper
│
├── stores/                       ← Zustand (xem mục 8)
│   ├── authStore.ts
│   ├── workspaceStore.ts
│   └── uiStore.ts
│
├── services/
│   ├── api.ts                    ← base fetch + token refresh
│   ├── notesService.ts
│   ├── workspaceService.ts
│   └── scheduleService.ts
│
├── types/
│   └── index.ts
│
└── utils/
    ├── theme.ts
    ├── noteMarkdown.ts
    └── textPatch.ts
```

---

## 8. State Management — Dùng Zustand

Hiện tại App.tsx đang là một "God component" với ~50 state variables, ~15 async functions. Cần tách ra.

### authStore

```typescript
interface AuthStore {
  tokens: TokenPair | null
  user: User | null
  setTokens: (t: TokenPair | null) => void
  setUser: (u: User | null) => void
  logout: () => void
}
```

### workspaceStore

```typescript
interface WorkspaceStore {
  workspaces: Workspace[]
  currentWorkspaceId: string | null  // derived từ URL params
  
  // Actions
  loadWorkspaces: () => Promise<void>
  createWorkspace: (name: string) => Promise<Workspace>
  renameWorkspace: (id: string, name: string) => Promise<void>
  deleteWorkspace: (id: string) => Promise<void>
}
```

Lưu ý: `currentWorkspaceId` nên được derive từ URL (useParams), không lưu trong store. Đây là điểm quan trọng để tránh inconsistency giữa URL và state.

### uiStore

```typescript
interface UiStore {
  isSidebarCollapsed: boolean
  isAskAIOpen: boolean
  isSearchOpen: boolean
  notifications: AppNotification[]
  // ... các UI state khác
}
```

---

## 9. Data Flow — Frontend ↔ Backend

### Pattern hiện tại (vấn đề)

```
App.tsx → requestWithAuth → API → setState (trong App.tsx)
```

Mọi thứ đổ vào App.tsx, gây khó maintain.

### Pattern mới đề xuất

```
Component → useHook → Service → api.ts → Backend
                    ↓
               Zustand Store ← (nếu cần global state)
                    ↓
               Component re-renders
```

### Ví dụ cụ thể cho Notes

```typescript
// hooks/useNotes.ts
export function useNotes(workspaceId: string) {
  const [notes, setNotes] = useState<AppNote[]>([])
  
  const load = useCallback(async () => {
    const data = await notesService.getByWorkspace(workspaceId)
    setNotes(data)
  }, [workspaceId])
  
  // Auto-reload khi workspaceId thay đổi
  useEffect(() => { void load() }, [load])
  
  const create = useCallback(async (parentId?: string) => {
    const note = await notesService.create({ workspaceId, parentId })
    setNotes(prev => [note, ...prev])
    return note
  }, [workspaceId])
  
  return { notes, create, load, /* ...other operations */ }
}
```

```typescript
// services/notesService.ts
export const notesService = {
  getByWorkspace: (workspaceId: string) =>
    api.get<ApiNote[]>(`/notes/workspaces/${workspaceId}`),
    
  create: (payload: NoteCreatePayload) =>
    api.post<ApiNote>('/notes', payload),
    
  patch: (noteId: string, patch: NotePatchRequest) =>
    api.post<ApiNote>(`/notes/${noteId}/patch`, patch),
    
  delete: (noteId: string) =>
    api.delete(`/notes/${noteId}`),
}
```

---

## 10. Danh sách thay đổi cần implement (ưu tiên)

### Phase 1 — Foundation (cần làm trước)

1. **Migrate routing sang workspace-centric URLs** — `/w/:workspaceId/notes/:noteId`
2. **Tách App.tsx** thành các hooks và stores nhỏ
3. **Di chuyển Home lên đầu sidebar**, tách global vs workspace navigation
4. **Cài Zustand** cho auth, workspace, UI state

### Phase 2 — Workspace CRUD

5. **WorkspaceCreateModal** — form tạo workspace mới
6. **Inline rename** cho workspace (double-click để edit)
7. **ConfirmDialog** cho delete workspace
8. **WorkspaceMembersModal** — manage members (owner only)
9. **Context menu** (3-dot) trên workspace item trong switcher

### Phase 3 — Home & Dashboard

10. **GlobalHome** — dashboard tổng hợp (recent notes, upcoming schedules, quick actions)
11. **WorkspaceDashboard** — landing page cho mỗi workspace
12. **Recent activity feed** — aggregate từ notes + records

### Phase 4 — UX polish

13. **Keyboard shortcuts** — `G H` cho Home, `G N` cho Notes, etc.
14. **URL-based workspace persistence** — workspace hiện tại lưu trong URL, không chỉ trong state
15. **Optimistic updates** cho note operations (tránh lag)
16. **Error boundaries** per-section thay vì global error state

---

## 11. Design System Guidelines

**Style**: Minimal productivity-focused, không phải minimalism thuần túy. Đủ visual hierarchy để scan nhanh, đủ whitespace để không choáng ngợp.

**Màu sắc hierarchy**:
- Primary actions (Create, Save) — `--text-primary` background
- Secondary actions (Cancel, Settings) — ghost/outline
- Destructive actions (Delete) — `--red` chỉ khi hover/confirm
- Workspace badges — màu từ role (owner=blue, editor=green, viewer=gray)

**Typography scale**:
- Page title: 20px 700
- Section header: 11px 700 uppercase
- Body: 13-14px 400/500
- Meta/caption: 11-12px 400

**Interaction patterns**:
- Single click → select/navigate
- Double click → inline edit
- Right click / 3-dot → context menu
- Drag → reorder/reparent (notes tree)
- Hover → show actions (delete, rename buttons)

**Responsive**:
- `> 1200px`: sidebar expanded + main content
- `900-1200px`: sidebar collapsible (default open)
- `< 900px`: sidebar as drawer (overlay)

---

## 12. Migration Path — Không break app hiện tại

Thay vì rewrite toàn bộ, làm từng bước:

**Bước 1**: Giữ nguyên App.tsx, tạo thêm các hooks (`useNotes`, `useWorkspace`) — extract logic ra khỏi component, state vẫn ở App.tsx nhưng logic tách ra.

**Bước 2**: Migrate routing sang workspace-centric URLs, đây là thay đổi visible nhất với user.

**Bước 3**: Tạo GlobalHome component, thay thế trang home hiện tại.

**Bước 4**: Tạo WorkspaceDashboard, thêm CRUD modals.

**Bước 5**: Migrate state sang Zustand, App.tsx trở thành thin shell.

Không nên rewrite toàn bộ trong một lần — quá nhiều rủi ro regression và mất nhiều thời gian debug.