import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { nanoid } from 'nanoid'
import { Settings, Trash2, Play, AlertCircle, CheckCircle2 } from 'lucide-react'
import {
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  addEdge,
  MarkerType,
  type Connection,
  type Node,
  type Edge,
  type OnSelectionChangeParams,
  type ReactFlowInstance,
} from 'reactflow'
import 'reactflow/dist/style.css'
import type {
  WorkflowNodeDef,
  WorkflowEdgeDef,
  WorkflowDefinitionSchema,
  WorkflowCreatePayload,
  WorkflowUpdatePayload,
  WorkflowStatus,
  TriggerType,
  WorkflowConflict,
} from '../types'
import { useWorkflows } from '../hooks/useWorkflows'
import { nodeTypes } from './workflow/nodes'
import { getNodeConfig } from './workflow/nodeConfig'
import { NodePalette } from './workflow/NodePalette'
import { WorkflowCanvas } from './workflow/WorkflowCanvas'
import { WorkflowToolbar } from './workflow/WorkflowToolbar'
import { WorkflowList } from './workflow/WorkflowList'
import { getConfigPanel } from './workflow/config'
import type { TemplateVar } from './workflow/config'

function getDefaultData(type: string): Record<string, unknown> {
  const config = getNodeConfig(type)
  return { label: config?.label ?? type, config: {} }
}

type WorkflowBuilderProps = {
  workspaceId: string | null
  workflowId: string | null
  onBack?: () => void
  onNavigate?: (workflowId: string) => void
  onWorkflowsChanged?: () => void
}

export function WorkflowBuilder(props: WorkflowBuilderProps) {
  return (
    <ReactFlowProvider>
      <WorkflowBuilderInner {...props} />
    </ReactFlowProvider>
  )
}

function WorkflowBuilderInner({ workspaceId, workflowId, onBack, onNavigate, onWorkflowsChanged }: WorkflowBuilderProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null)
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null)
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [selectedNode, setSelectedNode] = useState<Node | null>(null)
  const [jsonConfigDraft, setJsonConfigDraft] = useState<{ nodeId: string; text: string } | null>(null)

  const [workflowName, setWorkflowName] = useState('')
  const [workflowDescription, setWorkflowDescription] = useState('')
  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatus>('draft')
  const [currentWorkflowId, setCurrentWorkflowId] = useState<string | null>(null)

  // Multi-trigger support: every node whose type starts with "trigger." is
  // a trigger. The first one (canvas/array order — same rule the old
  // single-trigger derivation used) is the "primary" trigger, sent as the
  // workflow's own trigger_type/trigger_config exactly as before. Any
  // others are "supplementary" triggers, reconciled against
  // /workflows/{id}/triggers on save (see reconcileSupplementaryTriggers).
  // No separate triggerConfig state: node.data.config is already the
  // single source of truth for every node type via updateNodeConfig, so
  // deriving straight from it here avoids the two states going out of
  // sync (the bug that made a second trigger node overwrite the first's
  // config under the old design).
  const triggerNodes = useMemo(() => nodes.filter(n => n.type?.startsWith('trigger.')), [nodes])
  const primaryTriggerNode = triggerNodes[0]
  const supplementaryTriggerNodes = useMemo(() => triggerNodes.slice(1), [triggerNodes])

  const triggerType = useMemo<TriggerType>(() => {
    if (primaryTriggerNode?.type) {
      return primaryTriggerNode.type.replace('trigger.', '') as TriggerType
    }
    return 'manual'
  }, [primaryTriggerNode])

  const triggerConfig = useMemo<Record<string, unknown>>(
    () => (primaryTriggerNode?.data?.config as Record<string, unknown>) ?? {},
    [primaryTriggerNode],
  )

  const [view, setView] = useState<'list' | 'editor'>('list')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [conflictWarnings, setConflictWarnings] = useState<WorkflowConflict[]>([])
  const [nodeOutputs, setNodeOutputs] = useState<Record<string, { success: boolean; output: Record<string, unknown>; error: string | null }>>({})
  const [runningNodeId, setRunningNodeId] = useState<string | null>(null)

  const templateVars = useMemo<TemplateVar[]>(() => {
    const vars: TemplateVar[] = []

    const upstreamIds = selectedNode
      ? (() => {
          const ids: string[] = []
          const visited = new Set<string>()
          const queue = [selectedNode.id]
          while (queue.length > 0) {
            const current = queue.shift()!
            for (const edge of edges) {
              if (edge.target === current && !visited.has(edge.source)) {
                visited.add(edge.source)
                ids.push(edge.source)
                queue.push(edge.source)
              }
            }
          }
          return ids
        })()
      : []

    if (triggerType === 'schedule') {
      vars.push(
        { label: 'Trigger event name', value: '{{trigger.event}}' },
        { label: 'Schedule ID', value: '{{trigger.schedule_id}}' },
        { label: 'Run timestamp', value: '{{trigger.timestamp}}' },
        { label: 'Timezone', value: '{{trigger.timezone}}' },
      )
    } else if (triggerType === 'manual') {
      vars.push(
        { label: 'Trigger event name', value: '{{trigger.event}}' },
        { label: 'Manual input', value: '{{trigger.input}}' },
      )
    }

    for (const node of nodes) {
      if (!selectedNode) continue
      if (node.id === selectedNode.id) continue
      if (!upstreamIds.includes(node.id)) continue

      const label = node.data?.label as string | undefined
      if (label) {
        const output = nodeOutputs[node.id]
        if (output?.output) {
          for (const key of Object.keys(output.output)) {
            vars.push({ label: `"${label}" → ${key}`, value: `{{steps.${label}.${key}}}` })
          }
        }
      }
    }

    return vars
  }, [triggerType, nodes, nodeOutputs, selectedNode, edges])

  const wf = useWorkflows()

  const executeNodeRef = useRef<((nodeId: string, config: Record<string, unknown>) => void) | null>(null)

  const injectExecuteNode = useCallback((node: Node): Node => ({
    ...node,
    data: {
      ...node.data,
      onExecute: (config: Record<string, unknown>) => {
        executeNodeRef.current?.(node.id, config)
      },
    },
  }), [])

  const loadWorkflow = useCallback(async (id: string) => {
    const data = await wf.getWorkflow(id)
    if (!data) return
    setCurrentWorkflowId(data.id)
    setWorkflowName(data.name)
    setWorkflowDescription(data.description ?? '')
    setWorkflowStatus(data.status)

    const def = data.definition
    const flowNodes: Node[] = (def.nodes ?? []).map((n: WorkflowNodeDef) => {
      const nd = n.data as Record<string, unknown>
      const output = nd.output as { success: boolean; output: Record<string, unknown>; error: string | null } | undefined
      if (output) {
        setNodeOutputs(prev => ({ ...prev, [n.id]: output }))
      }
      return injectExecuteNode({ id: n.id, type: n.type, position: n.position, data: nd })
    })

    // Legacy workflows may carry trigger_config only on the API record,
    // not mirrored into the primary trigger node's own data.config — which
    // is now the single source of truth for it (see the triggerConfig
    // useMemo above). Seed it once so the canvas reflects what's actually
    // configured; every save from here on writes it back into node data.
    const primaryNode = flowNodes.find(n => n.type?.startsWith('trigger.'))
    if (primaryNode) {
      const nodeConfig = (primaryNode.data?.config as Record<string, unknown>) ?? {}
      if (Object.keys(nodeConfig).length === 0 && data.trigger_config && Object.keys(data.trigger_config).length > 0) {
        primaryNode.data = { ...primaryNode.data, config: data.trigger_config }
      }
    }

    const flowEdges: Edge[] = (def.edges ?? []).map((e: WorkflowEdgeDef) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.source_handle === null ? undefined : e.source_handle,
      targetHandle: e.target_handle === null ? undefined : e.target_handle,
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: '#b1b1b7' },
    }))
    setNodes(flowNodes)
    setEdges(flowEdges)
    setView('editor')
  }, [wf, setNodes, setEdges])

  useEffect(() => {
    if (workspaceId) {
      void wf.fetchWorkflows({ workspace_id: workspaceId })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId])

  useEffect(() => {
    if (workflowId && workflowId !== currentWorkflowId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void loadWorkflow(workflowId)
    }
  }, [workflowId, currentWorkflowId, loadWorkflow])

  useEffect(() => {
    if (workflowId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setView('editor')
    }
  }, [workflowId])

  const onConnect = useCallback((connection: Connection) => {
    setEdges(eds => addEdge({
      ...connection,
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: '#b1b1b7' },
    }, eds))
  }, [setEdges])

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [])

  const onDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    const type = event.dataTransfer.getData('application/reactflow')
    if (!type || !reactFlowInstance) return

    const position = reactFlowInstance.screenToFlowPosition({
      x: event.clientX,
      y: event.clientY,
    })

    const id = nanoid()
    const newNode: Node = injectExecuteNode({
      id,
      type,
      position,
      data: getDefaultData(type),
    })
    setNodes(nds => nds.concat(newNode))
  }, [reactFlowInstance, setNodes, injectExecuteNode])

  const onNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    setSelectedNode(node)
  }, [])

  const onPaneClick = useCallback(() => {
    setSelectedNode(null)
  }, [])

  const onSelectionChange = useCallback(({ nodes: selectedNodes }: OnSelectionChangeParams) => {
    if (selectedNodes.length === 1) {
      setSelectedNode(selectedNodes[0])
    } else if (selectedNodes.length === 0) {
      setSelectedNode(null)
    }
  }, [])

  const updateNodeConfig = useCallback((nodeId: string, config: Record<string, unknown>) => {
    setNodes(nds => nds.map(n => {
      if (n.id !== nodeId) return n
      return { ...n, data: { ...n.data, config } }
    }))
    setSelectedNode(prev => prev?.id === nodeId ? { ...prev, data: { ...prev.data, config } } : prev)
    // No separate sync needed: triggerType/triggerConfig are derived
    // straight from the trigger nodes' own data.config (see useMemo above).
  }, [setNodes])

  const buildDefinition = useCallback((): WorkflowDefinitionSchema => {
    return {
      nodes: nodes.map(n => ({
        id: n.id,
        type: n.type ?? '',
        position: n.position,
        data: n.data as Record<string, unknown>,
      })),
      edges: edges.map(e => ({
        id: e.id,
        source: e.source,
        target: e.target,
        source_handle: e.sourceHandle === null ? undefined : e.sourceHandle,
        target_handle: e.targetHandle === null ? undefined : e.targetHandle,
      })),
      variables: {},
    }
  }, [nodes, edges])

  // Reconcile canvas trigger nodes beyond the primary against
  // /workflows/{id}/triggers. Each supplementary node's backend row id is
  // stamped into node.data.triggerId once created (and round-trips through
  // definition.nodes on future loads, same as node.data.output already
  // does) — that's what lets a later save PATCH the right row instead of
  // creating a duplicate, and what lets a removed node's row get deleted.
  const reconcileSupplementaryTriggers = useCallback(async (workflowId: string) => {
    const existingTriggers = await wf.listWorkflowTriggers(workflowId)
    const existingIds = new Set(existingTriggers.map(t => t.id))
    const nodeTriggerIds = new Set(
      supplementaryTriggerNodes
        .map(n => n.data?.triggerId as string | undefined)
        .filter((id): id is string => !!id)
    )

    for (const trigger of existingTriggers) {
      if (!nodeTriggerIds.has(trigger.id)) {
        await wf.deleteWorkflowTrigger(workflowId, trigger.id)
      }
    }

    for (const node of supplementaryTriggerNodes) {
      const nodeTriggerType = (node.type ?? '').replace('trigger.', '') as TriggerType
      const config = (node.data?.config as Record<string, unknown>) ?? {}
      const existingId = node.data?.triggerId as string | undefined

      if (existingId && existingIds.has(existingId)) {
        await wf.updateWorkflowTrigger(workflowId, existingId, { trigger_config: config })
      } else {
        const created = await wf.createWorkflowTrigger(workflowId, {
          trigger_type: nodeTriggerType,
          trigger_config: config,
        })
        if (created) {
          const createdId = created.id
          setNodes(nds => nds.map(n => n.id === node.id ? { ...n, data: { ...n.data, triggerId: createdId } } : n))
        }
      }
    }
  }, [wf, supplementaryTriggerNodes, setNodes])

  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      const definition = buildDefinition()
      let workflowId = currentWorkflowId
      if (currentWorkflowId) {
        const payload: WorkflowUpdatePayload = {
          name: workflowName || 'Untitled Workflow',
          description: workflowDescription || undefined,
          definition,
          trigger_config: triggerConfig,
        }
        const updated = await wf.updateWorkflow(currentWorkflowId, payload)
        if (updated) {
          setWorkflowName(updated.name)
          setWorkflowStatus(updated.status)
        }
      } else {
        const payload: WorkflowCreatePayload = {
          name: workflowName || 'Untitled Workflow',
          description: workflowDescription || undefined,
          workspace_id: workspaceId ?? undefined,
          trigger_type: triggerType,
          trigger_config: triggerConfig,
          definition,
        }
        const created = await wf.createWorkflow(payload)
        if (created) {
          workflowId = created.id
          setCurrentWorkflowId(created.id)
          setWorkflowStatus(created.status)
        }
      }
      if (workflowId) {
        await reconcileSupplementaryTriggers(workflowId)
      }
      onWorkflowsChanged?.()
    } finally {
      setSaving(false)
    }
  }, [currentWorkflowId, workflowName, workflowDescription, triggerType, triggerConfig, workspaceId, wf, buildDefinition, reconcileSupplementaryTriggers, onWorkflowsChanged])

  const handleActivate = useCallback(async () => {
    if (!currentWorkflowId) return
    await handleSave()
    const updated = await wf.activateWorkflow(currentWorkflowId)
    if (updated && 'status' in updated) {
      setWorkflowStatus(updated.status)
      // A3: the activate response may carry conflict warnings (this
      // workflow duplicates the backend's own delivery for this event, or
      // another active workflow already covers it) — informational, the
      // workflow is still active either way.
      setConflictWarnings(updated.warnings ?? [])
    } else if (updated && 'error' in updated) {
      setError(`Failed to activate workflow: ${updated.error}`)
    }
  }, [currentWorkflowId, wf, handleSave])

  const handlePause = useCallback(async () => {
    if (!currentWorkflowId) return
    const updated = await wf.pauseWorkflow(currentWorkflowId)
    if (updated) setWorkflowStatus(updated.status)
  }, [currentWorkflowId, wf])

  const handleDelete = useCallback(async () => {
    if (!currentWorkflowId) return
    if (!window.confirm('Are you sure you want to delete this workflow?')) return
    const ok = await wf.deleteWorkflow(currentWorkflowId)
    if (ok) {
      setCurrentWorkflowId(null)
      setWorkflowName('')
      setWorkflowDescription('')
      setWorkflowStatus('draft')
      setNodes([])
      setEdges([])
      setView('list')
      if (workspaceId) void wf.fetchWorkflows({ workspace_id: workspaceId })
      onWorkflowsChanged?.()
    }
  }, [currentWorkflowId, wf, setNodes, setEdges, workspaceId, onWorkflowsChanged])

  const handleRemoveNode = useCallback(() => {
    setSelectedNode(prev => {
      if (!prev) return null
      setNodes(nds => nds.filter(n => n.id !== prev.id))
      setEdges(eds => eds.filter(e => e.source !== prev.id && e.target !== prev.id))
      return null
    })
  }, [setNodes, setEdges])

  const handleRun = useCallback(async () => {
    if (!currentWorkflowId) return
    setError(null)
    setSuccessMessage(null)
    await handleSave()

    // Auto-activate if not yet active
    if (workflowStatus !== 'active') {
      const updated = await wf.activateWorkflow(currentWorkflowId)
      if (!updated) {
        setError('Failed to activate workflow. Is the workflow service running?')
        return
      }
      if ('error' in updated) {
        setError(`Failed to activate workflow: ${updated.error}`)
        return
      }
      setWorkflowStatus(updated.status)
      setConflictWarnings(updated.warnings ?? [])
    }

    const result = await wf.triggerWorkflow(currentWorkflowId)
    if (result && 'instance_id' in result) {
      setSuccessMessage(`Workflow triggered (ID: ${result.instance_id.slice(0, 8)}…)`)
    } else if (result && 'error' in result) {
      setError(`Failed to trigger workflow: ${result.error}`)
    }
  }, [currentWorkflowId, wf, handleSave, workflowStatus])

  const handleRunNode = useCallback(async (nodeId: string, config: Record<string, unknown>) => {
    if (!currentWorkflowId) {
      setError('Please save the workflow first before running a node.')
      return
    }
    setRunningNodeId(nodeId)
    setError(null)
    setSuccessMessage(null)
    try {
      // Build trigger_data from trigger type
      const trigger_data: Record<string, unknown> = {}
      if (triggerType === 'manual') {
        trigger_data.event = 'manual.trigger'
        trigger_data.input = {}
      } else if (triggerType === 'schedule') {
        trigger_data.event = 'schedule.trigger'
        trigger_data.schedule_id = triggerConfig.schedule_id
        trigger_data.timestamp = new Date().toISOString()
        trigger_data.timezone = triggerConfig.timezone ?? 'UTC'
      } else if (triggerType === 'webhook') {
        trigger_data.event = 'webhook.received'
      } else if (triggerType === 'internal_event') {
        trigger_data.event = triggerConfig.event ?? 'unknown.event'
      }

      // Build previous_outputs from already-executed nodes
      const previous_outputs: Record<string, unknown> = {}
      for (const [nid, no] of Object.entries(nodeOutputs)) {
        previous_outputs[nid] = no.output
      }

      const result = await wf.executeNode(currentWorkflowId, nodeId, {
        config,
        trigger_data,
        previous_outputs,
      })
      if (result) {
        setNodeOutputs(prev => ({ ...prev, [nodeId]: result }))
        setNodes(nds => nds.map(n =>
          n.id === nodeId ? { ...n, data: { ...n.data, output: result } } : n
        ))
        if (!result.success && result.error) {
          setError(result.error)
        }
      } else {
        setError('Failed to execute node. Is the workflow service running?')
      }
    } finally {
      setRunningNodeId(null)
    }
  }, [currentWorkflowId, wf, setNodes, triggerType, triggerConfig, nodeOutputs])

  useEffect(() => { executeNodeRef.current = handleRunNode }, [handleRunNode])

  const handleNewWorkflow = useCallback(() => {
    setCurrentWorkflowId(null)
    setWorkflowName('')
    setWorkflowDescription('')
    setWorkflowStatus('draft')
    setNodes([])
    setEdges([])
    setSelectedNode(null)
    setView('editor')
  }, [setNodes, setEdges])

  const handlePaletteDragStart = useCallback((event: React.DragEvent, type: string) => {
    event.dataTransfer.setData('application/reactflow', type)
    event.dataTransfer.effectAllowed = 'move'
  }, [])

  const handleAddStickyNote = useCallback(() => {
    if (!reactFlowInstance) return
    const center = reactFlowInstance.screenToFlowPosition({
      x: window.innerWidth / 2,
      y: window.innerHeight / 2,
    })
    const id = nanoid()
    const newNode: Node = injectExecuteNode({
      id,
      type: 'sticky_note',
      position: center,
      data: { label: 'Sticky Note', content: '', color: 'yellow' },
    })
    setNodes(nds => nds.concat(newNode))
  }, [reactFlowInstance, setNodes, injectExecuteNode])

  const statusBadge = useMemo(() => {
    const colors: Record<WorkflowStatus, string> = {
      draft: 'var(--text-tertiary)',
      active: 'var(--green)',
      paused: 'var(--yellow)',
      archived: 'var(--text-disabled)',
    }
    return { label: workflowStatus, color: colors[workflowStatus] ?? 'var(--text-tertiary)' }
  }, [workflowStatus])

  if (view === 'list') {
    return (
      <WorkflowList
        workflows={wf.workflows}
        loading={wf.loading}
        onSelect={(id) => {
          loadWorkflow(id)
          if (onNavigate) onNavigate(id)
        }}
        onNew={handleNewWorkflow}
      />
    )
  }

  return (
    <div className="wf-page wf-root">
      <WorkflowToolbar
        workflowName={workflowName}
        workflowStatus={workflowStatus}
        currentWorkflowId={currentWorkflowId}
        saving={saving}
        statusBadge={statusBadge}
        onNameChange={setWorkflowName}
        onBack={() => {
          setView('list')
          if (onBack) onBack()
          if (workspaceId) void wf.fetchWorkflows({ workspace_id: workspaceId })
        }}
        onSave={handleSave}
        onActivate={handleActivate}
        onPause={handlePause}
        onRun={handleRun}
        onDelete={handleDelete}
      />

      {error && (
        <div className="wf-error-banner">
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)}>×</button>
        </div>
      )}
      {successMessage && (
        <div className="wf-success-banner">
          <span>{successMessage}</span>
          <button type="button" onClick={() => setSuccessMessage(null)}>×</button>
        </div>
      )}
      {conflictWarnings.length > 0 && (
        <div className="wf-warning-banner">
          <div className="wf-warning-banner-header">
            <span>Có thể bắn thông báo trùng</span>
            <button type="button" onClick={() => setConflictWarnings([])}>×</button>
          </div>
          <ul>
            {conflictWarnings.map((w, i) => (
              <li key={i}>{w.message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="wf-body">
        <NodePalette onDragStart={handlePaletteDragStart} onAddStickyNote={handleAddStickyNote} />

        <WorkflowCanvas
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onDrop={onDrop}
          onDragOver={onDragOver}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          onSelectionChange={onSelectionChange}
          onInit={setReactFlowInstance}
          nodeTypes={nodeTypes}
          reactFlowWrapperRef={reactFlowWrapper}
        />

        {selectedNode && selectedNode.type !== 'sticky_note' && (
          <aside className="wf-config">
            <div className="wf-config-header">
              <div className="wf-config-header-left">
                <h2 className="wf-config-title">Node Configuration</h2>
                <p className="wf-config-subtitle">PARAMETERS</p>
              </div>
              <Settings size={18} style={{ color: 'var(--text-tertiary)' }} />
            </div>
            <div className="wf-config-body">
              <div className="wf-config-field">
                <label className="wf-config-label">TYPE</label>
                <div className="wf-config-value">{selectedNode.type}</div>
              </div>
              <div className="wf-config-field">
                <label className="wf-config-label">LABEL</label>
                <input
                  type="text"
                  className="wf-config-input"
                  value={selectedNode.data.label as string ?? ''}
                  onChange={e => {
                    const newLabel = e.target.value
                    setNodes(nds => nds.map(n => n.id === selectedNode.id ? { ...n, data: { ...n.data, label: newLabel } } : n))
                    setSelectedNode(prev => prev?.id === selectedNode.id ? { ...prev, data: { ...prev.data, label: newLabel } } : prev)
                  }}
                />
              </div>
              {(() => {
                const ConfigPanel = getConfigPanel(selectedNode.type ?? '')
                if (ConfigPanel) {
                  return (
                    <ConfigPanel
                      key={selectedNode.id}
                      config={(selectedNode.data.config as Record<string, unknown>) ?? {}}
                      onChange={(cfg) => updateNodeConfig(selectedNode.id, cfg)}
                      templateVars={templateVars}
                    />
                  )
                }
                return (
                  <div className="wf-config-field">
                    <label className="wf-config-label">CONFIG (JSON)</label>
                    <div className="wf-config-textarea-wrap">
                      <textarea
                        className="wf-config-textarea"
                        rows={6}
                        value={
                          jsonConfigDraft?.nodeId === selectedNode.id
                            ? jsonConfigDraft.text
                            : JSON.stringify(selectedNode.data.config ?? {}, null, 2)
                        }
                        onChange={e => {
                          const text = e.target.value
                          setJsonConfigDraft({ nodeId: selectedNode.id, text })
                          try {
                            const parsed = JSON.parse(text)
                            updateNodeConfig(selectedNode.id, parsed)
                          } catch {
                            // Allow typing/pasting invalid JSON temporarily
                          }
                        }}
                      />
                    </div>
                  </div>
                )
              })()}
              {selectedNode.type?.startsWith('trigger.') && (
                <div className="wf-config-field">
                  <label className="wf-config-label">TRIGGER TYPE</label>
                  <div className="wf-config-value">
                    {selectedNode.type.replace('trigger.', '').replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase())}
                  </div>
                  <div className="wf-config-hint">
                    {selectedNode.id === primaryTriggerNode?.id
                      ? 'Primary trigger — determines the workflow\'s main trigger_type'
                      : 'Additional trigger — runs alongside the primary trigger'}
                  </div>
                </div>
              )}
              {(() => {
                const nodeOutput = nodeOutputs[selectedNode.id] ?? (selectedNode.data?.output as { success: boolean; output: Record<string, unknown>; error: string | null } | undefined)
                if (nodeOutput) {
                  return (
                    <div className="wf-config-field">
                      <label className="wf-config-label">OUTPUT</label>
                      <div className={`wf-node-output ${nodeOutput.success ? 'wf-node-output--success' : 'wf-node-output--error'}`}>
                        <div className="wf-node-output-header">
                          {nodeOutput.success
                            ? <CheckCircle2 size={14} style={{ color: 'var(--green)' }} />
                            : <AlertCircle size={14} style={{ color: 'var(--red)' }} />}
                          <span>{nodeOutput.success ? 'Success' : 'Failed'}</span>
                        </div>
                        {nodeOutput.error && <div className="wf-node-output-error">{nodeOutput.error}</div>}
                        {nodeOutput.output && Object.keys(nodeOutput.output).length > 0 && (
                          <pre className="wf-node-output-json">{JSON.stringify(nodeOutput.output, null, 2)}</pre>
                        )}
                      </div>
                    </div>
                  )
                }
                return null
              })()}
              {selectedNode.type !== 'sticky_note' ? (
                <div className="wf-config-field">
                  <button
                    type="button"
                    className="wf-config-run-btn"
                    onClick={() => handleRunNode(selectedNode.id, (selectedNode.data.config as Record<string, unknown>) ?? {})}
                    disabled={runningNodeId === selectedNode.id}
                  >
                    {runningNodeId === selectedNode.id ? (
                      <>Running...</>
                    ) : (
                      <><Play size={14} /> Run Node</>
                    )}
                  </button>
                </div>
              ) : null}
            </div>
            <div className="wf-config-actions">
              <button type="button" className="wf-config-remove-btn" onClick={handleRemoveNode}>
                <Trash2 size={16} />
                Remove Node
              </button>
            </div>
          </aside>
        )}
      </div>
    </div>
  )
}
