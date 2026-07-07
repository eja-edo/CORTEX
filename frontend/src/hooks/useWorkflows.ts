import { useCallback, useState } from 'react'
import type {
  WorkflowResponse,
  WorkflowListResponse,
  WorkflowCreatePayload,
  WorkflowUpdatePayload,
} from '../types'
import { getCurrentTokens, setCurrentTokens, ApiError } from '../services/api'

async function workflowRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let tokens = getCurrentTokens()
  if (!tokens?.accessToken) throw new Error('Please login first')

  const headers = new Headers(init?.headers ?? {})
  headers.set('Authorization', `Bearer ${tokens.accessToken}`)
  const url = `/api${path}`
  let response = await fetch(url, { ...init, headers })

  if (response.status === 401 && tokens.refreshToken) {
    const refreshRes = await fetch(`${import.meta.env.VITE_APIhash_BASE_URL ?? 'http://localhost:8000/api'}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: tokens.refreshToken }),
    })
    if (refreshRes.ok) {
      const data = await refreshRes.json()
      tokens = { accessToken: data.access_token, refreshToken: data.refresh_token }
      setCurrentTokens(tokens)
      const retryHeaders = new Headers(init?.headers ?? {})
      retryHeaders.set('Authorization', `Bearer ${tokens.accessToken}`)
      response = await fetch(url, { ...init, headers: retryHeaders })
    }
  }

  const text = await response.text()
  const body = text ? JSON.parse(text) : null
  if (!response.ok) throw new ApiError(body?.detail ?? `Request failed (${response.status})`, response.status)
  return body as T
}

export function useWorkflows() {
  const [workflows, setWorkflows] = useState<WorkflowResponse[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  const fetchWorkflows = useCallback(async (params?: {
    workspace_id?: string
    status?: string
    page?: number
    page_size?: number
  }): Promise<void> => {
    setLoading(true)
    try {
      const searchParams = new URLSearchParams()
      if (params?.workspace_id) searchParams.set('workspace_id', params.workspace_id)
      if (params?.status) searchParams.set('status', params.status)
      if (params?.page) searchParams.set('page', String(params.page))
      if (params?.page_size) searchParams.set('page_size', String(params.page_size))
      const qs = searchParams.toString()
      const data = await workflowRequest<WorkflowListResponse>(`/v1/workflows${qs ? `?${qs}` : ''}`)
      setWorkflows(data.items)
      setTotal(data.total)
    } catch (error) {
      console.error('Cannot load workflows:', error)
    } finally {
      setLoading(false)
    }
  }, [])

  const getWorkflow = useCallback(async (workflowId: string): Promise<WorkflowResponse | null> => {
    try {
      return await workflowRequest<WorkflowResponse>(`/v1/workflows/${workflowId}`)
    } catch (error) {
      console.error('Cannot get workflow:', error)
      return null
    }
  }, [])

  const createWorkflow = useCallback(async (payload: WorkflowCreatePayload): Promise<WorkflowResponse | null> => {
    try {
      const created = await workflowRequest<WorkflowResponse>('/v1/workflows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      setWorkflows(prev => [created, ...prev])
      setTotal(prev => prev + 1)
      return created
    } catch (error) {
      console.error('Cannot create workflow:', error)
      return null
    }
  }, [])

  const updateWorkflow = useCallback(async (workflowId: string, payload: WorkflowUpdatePayload): Promise<WorkflowResponse | null> => {
    try {
      const updated = await workflowRequest<WorkflowResponse>(`/v1/workflows/${workflowId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      setWorkflows(prev => prev.map(w => w.id === workflowId ? updated : w))
      return updated
    } catch (error) {
      console.error('Cannot update workflow:', error)
      return null
    }
  }, [])

  const deleteWorkflow = useCallback(async (workflowId: string): Promise<boolean> => {
    try {
      await workflowRequest<void>(`/v1/workflows/${workflowId}`, { method: 'DELETE' })
      setWorkflows(prev => prev.filter(w => w.id !== workflowId))
      setTotal(prev => Math.max(0, prev - 1))
      return true
    } catch (error) {
      console.error('Cannot delete workflow:', error)
      return false
    }
  }, [])

  const activateWorkflow = useCallback(async (workflowId: string): Promise<WorkflowResponse | null> => {
    try {
      const updated = await workflowRequest<WorkflowResponse>(`/v1/workflows/${workflowId}/activate`, { method: 'POST' })
      setWorkflows(prev => prev.map(w => w.id === workflowId ? updated : w))
      return updated
    } catch (error) {
      console.error('Cannot activate workflow:', error)
      return null
    }
  }, [])

  const pauseWorkflow = useCallback(async (workflowId: string): Promise<WorkflowResponse | null> => {
    try {
      const updated = await workflowRequest<WorkflowResponse>(`/v1/workflows/${workflowId}/pause`, { method: 'POST' })
      setWorkflows(prev => prev.map(w => w.id === workflowId ? updated : w))
      return updated
    } catch (error) {
      console.error('Cannot pause workflow:', error)
      return null
    }
  }, [])

  const triggerWorkflow = useCallback(async (workflowId: string, inputData?: Record<string, unknown>): Promise<{ instance_id: string } | null> => {
    try {
      return await workflowRequest<{ instance_id: string }>(`/v1/workflows/${workflowId}/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input_data: inputData ?? {} }),
      })
    } catch (error) {
      console.error('Cannot trigger workflow:', error)
      return null
    }
  }, [])

  type ExecuteNodeResponse = {
    success: boolean
    output: Record<string, unknown>
    error: string | null
  }

  type ExecuteNodeInput = {
    config: Record<string, unknown>
    trigger_data?: Record<string, unknown>
    previous_outputs?: Record<string, unknown>
  }

  const executeNode = useCallback(async (
    workflowId: string,
    nodeId: string,
    input: ExecuteNodeInput
  ): Promise<ExecuteNodeResponse | null> => {
    try {
      return await workflowRequest<ExecuteNodeResponse>(`/v1/workflows/${workflowId}/nodes/${nodeId}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      })
    } catch (error) {
      console.error('Cannot execute node:', error)
      return null
    }
  }, [])

  return {
    workflows,
    total,
    loading,
    fetchWorkflows,
    getWorkflow,
    createWorkflow,
    updateWorkflow,
    deleteWorkflow,
    activateWorkflow,
    pauseWorkflow,
    triggerWorkflow,
    executeNode,
  }
}
