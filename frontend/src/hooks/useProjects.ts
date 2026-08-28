import { useEffect } from 'react'
import { useProjectStore } from '../stores/projectStore'

/**
 * Dự án của người dùng, cho sidebar và màn Việc.
 *
 * Hook lo việc nạp lần đầu, store giữ dữ
 * liệu, nên mọi màn hình đọc cùng một danh sách và một lần đổi tên hiện ra
 * ở tất cả chúng mà không cần refetch.
 *
 * `currentProject` suy ra tại đây thay vì lưu thành state riêng — một id
 * và một object của cùng một thứ là hai nguồn sự thật, và chúng sẽ lệch
 * nhau đúng vào lúc danh sách vừa được nạp lại.
 */
export function useProjects() {
    const projects = useProjectStore((state) => state.projects)
    const isLoading = useProjectStore((state) => state.isLoading)
    const error = useProjectStore((state) => state.error)
    const hasLoaded = useProjectStore((state) => state.hasLoaded)
    const openProjectId = useProjectStore((state) => state.openProjectId)
    const fetchAll = useProjectStore((state) => state.fetchAll)
    const setOpenProject = useProjectStore((state) => state.setOpenProject)
    const create = useProjectStore((state) => state.create)
    const rename = useProjectStore((state) => state.rename)
    const moveTask = useProjectStore((state) => state.moveTask)

    useEffect(() => {
        if (!hasLoaded) void fetchAll()
    }, [hasLoaded, fetchAll])

    return {
        projects,
        currentProject: projects.find((p) => p.id === openProjectId) ?? null,
        openProjectId,
        isLoading,
        error,
        fetchAll,
        setOpenProject,
        create: async (name: string) => {
            await create(name)
        },
        rename,
        moveTask,
    }
}
