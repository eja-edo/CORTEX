import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * `useProjectStore` — DESIGN 10.2.
 *
 * Điều đáng canh không phải CRUD mà là **phạm vi của "dự án đang mở"**: nó
 * là một scope của giao diện, không phải một ngữ cảnh ngầm. Nó quyết định
 * màn Việc liệt kê gì, và **không** quyết định gì khác — đặc biệt là không
 * bao giờ đi tới agent (DESIGN 9.2 loại bỏ "dự án hiện tại" ở mức phiên vì
 * nó tạo ra kiểu hỏng im lặng tệ nhất: agent thao tác nhầm dự án và không
 * ai biết).
 */

const listProjects = vi.fn()
const createProject = vi.fn()
const moveTaskToProject = vi.fn()

vi.mock('../../services/api', () => ({
    listProjects: (...args: unknown[]) => listProjects(...args),
    createProject: (...args: unknown[]) => createProject(...args),
    moveTaskToProject: (...args: unknown[]) => moveTaskToProject(...args),
}))

const { useProjectStore } = await import('../projectStore')
const { useTaskStore } = await import('../taskStore')

function project(id: string, name: string) {
    return {
        id,
        name,
        status: 'active' as const,
        origin: 'derived' as const,
        deadline: null,
        deadline_is_manual: false,
        source_channel_id: null,
        open_task_count: 0,
        completed_task_count: 0,
        member_count: 1,
        risk: 0,
        created_at: '2026-08-01T00:00:00',
        updated_at: '2026-08-01T00:00:00',
    }
}

beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    useProjectStore.setState({
        projects: [],
        isLoading: false,
        hasLoaded: false,
        error: null,
        openProjectId: null,
    })
})

describe('fetchAll', () => {
    it('picks a project to open when nothing is chosen yet', async () => {
        // Một màn Việc không có dự án nào được chọn là một trang trống
        // không nói được vì sao nó trống.
        listProjects.mockResolvedValue([project('a', 'Alpha'), project('b', 'Beta')])

        await useProjectStore.getState().fetchAll()

        expect(useProjectStore.getState().openProjectId).toBe('a')
    })

    it('keeps the chosen project when it is still there', async () => {
        useProjectStore.setState({ openProjectId: 'b' })
        listProjects.mockResolvedValue([project('a', 'Alpha'), project('b', 'Beta')])

        await useProjectStore.getState().fetchAll()

        expect(useProjectStore.getState().openProjectId).toBe('b')
    })

    it('recovers when the remembered project is gone', async () => {
        // Đóng ở nơi khác, hoặc localStorage còn sót từ tài khoản trước.
        // Bộ chuyển không được trỏ vào hư không.
        useProjectStore.setState({ openProjectId: 'deleted' })
        listProjects.mockResolvedValue([project('a', 'Alpha')])

        await useProjectStore.getState().fetchAll()

        expect(useProjectStore.getState().openProjectId).toBe('a')
    })

    it('records the error instead of throwing at the screen', async () => {
        listProjects.mockRejectedValue(new Error('mạng hỏng'))

        await useProjectStore.getState().fetchAll()

        expect(useProjectStore.getState().error).toBe('mạng hỏng')
        expect(useProjectStore.getState().hasLoaded).toBe(true)
    })
})

describe('setOpenProject', () => {
    it('remembers the choice across reloads', () => {
        useProjectStore.getState().setOpenProject('a')
        expect(window.localStorage.getItem('cortex_open_project')).toBe('a')
    })

    it('survives storage being unavailable', () => {
        // Cửa sổ riêng tư và trình duyệt chặn site data đều ném ở đây. Ghi
        // nhớ lựa chọn là tiện ích; không ghi nhớ được thì vẫn phải đổi
        // được dự án trong phiên này.
        const setItem = vi
            .spyOn(Storage.prototype, 'setItem')
            .mockImplementation(() => {
                throw new Error('blocked')
            })

        expect(() => useProjectStore.getState().setOpenProject('a')).not.toThrow()
        expect(useProjectStore.getState().openProjectId).toBe('a')

        setItem.mockRestore()
    })
})

describe('moveTask', () => {
    it('patches the task cache so every screen agrees at once', async () => {
        // `useTaskStore` là nguồn duy nhất cho Hôm nay, Việc, checklist sự
        // kiện và sub-task. Sửa dự án ở một chỗ mà không patch cache sẽ để
        // các màn khác hiện dữ liệu cũ mà không có gì báo cho chúng biết.
        useTaskStore.setState({
            tasks: [{ id: 't1', project_id: 'a', title: 'nộp spec' } as never],
        })
        moveTaskToProject.mockResolvedValue({ id: 't1', project_id: 'b', title: 'nộp spec' })
        listProjects.mockResolvedValue([project('a', 'Alpha'), project('b', 'Beta')])

        await useProjectStore.getState().moveTask('t1', 'b')

        expect(useTaskStore.getState().tasks[0].project_id).toBe('b')
        // Số việc mở của cả hai dự án vừa đổi — nạp lại rẻ hơn là tự tính
        // lại và sai một cách khó thấy.
        expect(listProjects).toHaveBeenCalled()
    })
})

describe('create', () => {
    it('opens the project it just made', async () => {
        // Người dùng vừa gõ tên một dự án; không mở nó ra là bắt họ làm
        // thêm một bước cho một ý định đã rõ ràng.
        createProject.mockResolvedValue(project('c', 'Gamma'))

        await useProjectStore.getState().create('Gamma')

        expect(useProjectStore.getState().openProjectId).toBe('c')
        expect(useProjectStore.getState().projects.map((p) => p.id)).toContain('c')
    })
})

describe('nạp khi chưa đăng nhập', () => {
    it('không khoá vĩnh viễn sau một lần hỏng vì thiếu token', async () => {
        // Store nạp lần đầu lúc mount, trước khi `auth.tokens` có. Lần đó
        // ném "Please login first". Nếu `fetchAll` sau đăng nhập không chạy
        // lại được, bộ chuyển đứng im ở "Chưa có dự án" cho tới khi tải lại
        // trang — đúng lỗi đã xảy ra trên UI thật.
        listProjects.mockRejectedValueOnce(new Error('Please login first'))
        await useProjectStore.getState().fetchAll()
        expect(useProjectStore.getState().projects).toEqual([])

        listProjects.mockResolvedValueOnce([project('a', 'Alpha')])
        await useProjectStore.getState().fetchAll()

        expect(useProjectStore.getState().projects.map((p) => p.name)).toEqual(['Alpha'])
        expect(useProjectStore.getState().openProjectId).toBe('a')
        // Lỗi cũ phải được dọn, nếu không màn hình hiện dữ liệu đúng kèm
        // một thông báo lỗi cũ nằm cạnh.
        expect(useProjectStore.getState().error).toBeNull()
    })
})
