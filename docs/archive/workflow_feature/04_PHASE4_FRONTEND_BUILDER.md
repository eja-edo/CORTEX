# PHASE 4 — FRONTEND BUILDER
## React Flow Visual Workflow Builder

> **Thời gian**: Tuần 7–8 (10 ngày làm việc)  
> **Prerequisite**: Phase 2 hoàn thành — API CRUD + Actions endpoint  
> **Có thể chạy song song với Phase 3**  
> **Mục tiêu**: User kéo thả để tạo workflow trên browser, lưu lên API  
> **Output cuối phase**: Workflow builder hoạt động đầy đủ với save/load từ API

---

## 1. Tổng quan công việc Phase 4

```
Tuần 7                              Tuần 8
─────────────────────────────────── ───────────────────────────────────
Day 1:   Install deps + routing     Day 6-7: Node config panels
Day 2-3: Canvas + basic nodes       Day 8:   Execution history view
Day 4-5: Node palette + drag-drop   Day 9-10: Save/load + activate UI
```

---

## 2. Cài đặt dependencies

Thêm vào `frontend/package.json`:

```bash
npm install reactflow @reactflow/core @reactflow/controls @reactflow/minimap @reactflow/background
npm install @radix-ui/react-dialog @radix-ui/react-select @radix-ui/react-tabs
npm install zustand  # đã có trong Cortex
npm install react-hook-form zod @hookform/resolvers
```

> **Lưu ý**: Cortex đang dùng React 19 và Vite 8. React Flow hỗ trợ React 18+. Kiểm tra compatibility trước khi install.

---

## 3. Cấu trúc thư mục Frontend

```
frontend/src/
├── pages/
│   └── workflows/                  ← Thư mục mới
│       ├── index.tsx               ← /workflows — danh sách workflows
│       ├── [id]/
│       │   ├── builder.tsx         ← /workflows/:id/builder — React Flow canvas
│       │   └── executions.tsx      ← /workflows/:id/executions — execution history
│       └── new.tsx                 ← /workflows/new — tạo workflow mới
├── components/
│   └── workflow/                   ← Thư mục mới
│       ├── WorkflowCanvas.tsx      ← React Flow wrapper
│       ├── NodePalette.tsx         ← Panel trái — drag source nodes
│       ├── ConfigPanel.tsx         ← Panel phải — config node được select
│       ├── WorkflowToolbar.tsx     ← Toolbar trên — Save, Activate, Run
│       ├── ExecutionHistory.tsx    ← Danh sách execution instances
│       ├── nodes/
│       │   ├── TriggerNode.tsx     ← Custom node cho triggers
│       │   ├── ActionNode.tsx      ← Custom node cho actions
│       │   └── index.ts            ← Export nodeTypes map
│       └── panels/
│           ├── TriggerConfigPanel.tsx
│           └── ActionConfigPanel.tsx
├── hooks/
│   └── workflow/
│       ├── useWorkflowEditor.ts    ← State management cho builder
│       ├── useWorkflowApi.ts       ← API calls
│       └── useExecutions.ts
├── stores/
│   └── workflowStore.ts            ← Zustand store
└── types/
    └── workflow.ts                 ← TypeScript types
```

---

## 4. TypeScript Types

**`frontend/src/types/workflow.ts`**

```typescript
// Enums
export type WorkflowStatus = 'draft' | 'active' | 'paused' | 'archived';
export type TriggerType = 'internal_event' | 'webhook' | 'schedule' | 'manual';
export type ExecutionStatus = 'pending' | 'running' | 'waiting' | 'completed' | 'failed' | 'cancelled';

// Node/Edge types (React Flow compatible)
export interface NodePosition {
  x: number;
  y: number;
}

export interface WorkflowNodeData {
  label: string;
  nodeType: string;        // "trigger.internal_event", "action.create_note", etc.
  config: Record<string, unknown>;
  isConfigured: boolean;   // true khi user đã điền đủ config
}

export interface WorkflowNode {
  id: string;
  type: string;            // "triggerNode" | "actionNode" — React Flow node type
  position: NodePosition;
  data: WorkflowNodeData;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
}

export interface WorkflowDefinition {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  variables: Record<string, unknown>;
}

// API types
export interface Workflow {
  id: string;
  user_id: string;
  workspace_id?: string;
  name: string;
  description?: string;
  status: WorkflowStatus;
  version: number;
  trigger_type: TriggerType;
  trigger_config: Record<string, unknown>;
  definition: WorkflowDefinition;
  webhook_url?: string;
  created_at: string;
  updated_at: string;
}

export interface WorkflowListResponse {
  items: Workflow[];
  total: number;
  page: number;
  page_size: number;
}

export interface StepExecution {
  id: string;
  node_id: string;
  node_type: string;
  status: ExecutionStatus;
  input_data?: Record<string, unknown>;
  output_data?: Record<string, unknown>;
  error_message?: string;
  started_at?: string;
  completed_at?: string;
}

export interface WorkflowInstance {
  id: string;
  workflow_id: string;
  status: ExecutionStatus;
  trigger_data?: Record<string, unknown>;
  output?: Record<string, unknown>;
  error_message?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
  steps: StepExecution[];
}

// Available actions/triggers (từ API)
export interface ActionDefinition {
  type: string;
  display_name: string;
  description: string;
  config_schema: Record<string, unknown>;
}
```

---

## 5. Zustand Store

**`frontend/src/stores/workflowStore.ts`**

```typescript
import { create } from 'zustand';
import { applyNodeChanges, applyEdgeChanges, NodeChange, EdgeChange, addEdge, Connection } from 'reactflow';
import type { Workflow, WorkflowNode, WorkflowEdge, ActionDefinition } from '../types/workflow';

interface WorkflowEditorState {
  // Current workflow being edited
  workflow: Workflow | null;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  isDirty: boolean;          // true khi có unsaved changes
  isSaving: boolean;
  
  // Selected node for config panel
  selectedNodeId: string | null;
  
  // Available actions from API
  availableActions: ActionDefinition[];
  availableTriggers: ActionDefinition[];
  
  // Actions
  setWorkflow: (workflow: Workflow) => void;
  setNodes: (nodes: WorkflowNode[]) => void;
  setEdges: (edges: WorkflowEdge[]) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  addNode: (node: WorkflowNode) => void;
  updateNodeConfig: (nodeId: string, config: Record<string, unknown>) => void;
  selectNode: (nodeId: string | null) => void;
  setAvailableActions: (actions: ActionDefinition[], triggers: ActionDefinition[]) => void;
  setIsSaving: (saving: boolean) => void;
  markSaved: () => void;
}

export const useWorkflowStore = create<WorkflowEditorState>((set, get) => ({
  workflow: null,
  nodes: [],
  edges: [],
  isDirty: false,
  isSaving: false,
  selectedNodeId: null,
  availableActions: [],
  availableTriggers: [],
  
  setWorkflow: (workflow) => set({
    workflow,
    nodes: (workflow.definition?.nodes || []) as WorkflowNode[],
    edges: (workflow.definition?.edges || []) as WorkflowEdge[],
    isDirty: false,
  }),
  
  setNodes: (nodes) => set({ nodes, isDirty: true }),
  setEdges: (edges) => set({ edges, isDirty: true }),
  
  onNodesChange: (changes) => set((state) => ({
    nodes: applyNodeChanges(changes, state.nodes) as WorkflowNode[],
    isDirty: true,
  })),
  
  onEdgesChange: (changes) => set((state) => ({
    edges: applyEdgeChanges(changes, state.edges) as WorkflowEdge[],
    isDirty: true,
  })),
  
  onConnect: (connection) => set((state) => ({
    edges: addEdge({ ...connection, id: `edge-${Date.now()}` }, state.edges) as WorkflowEdge[],
    isDirty: true,
  })),
  
  addNode: (node) => set((state) => ({
    nodes: [...state.nodes, node],
    isDirty: true,
  })),
  
  updateNodeConfig: (nodeId, config) => set((state) => ({
    nodes: state.nodes.map(n =>
      n.id === nodeId
        ? { ...n, data: { ...n.data, config, isConfigured: true } }
        : n
    ),
    isDirty: true,
  })),
  
  selectNode: (nodeId) => set({ selectedNodeId: nodeId }),
  
  setAvailableActions: (actions, triggers) => set({ availableActions: actions, availableTriggers: triggers }),
  
  setIsSaving: (isSaving) => set({ isSaving }),
  
  markSaved: () => set({ isDirty: false }),
}));
```

---

## 6. Custom React Flow Nodes

**`frontend/src/components/workflow/nodes/TriggerNode.tsx`**

```tsx
import React from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { Zap } from 'lucide-react';
import type { WorkflowNodeData } from '../../../types/workflow';

const TRIGGER_LABELS: Record<string, string> = {
  'trigger.internal_event': 'Cortex Event',
  'trigger.webhook': 'Webhook',
  'trigger.manual': 'Manual',
  'trigger.schedule': 'Schedule',
};

export function TriggerNode({ data, selected }: NodeProps<WorkflowNodeData>) {
  const label = TRIGGER_LABELS[data.nodeType] || data.nodeType;
  const configuredEvent = (data.config as { event?: string }).event;
  
  return (
    <div className={`
      workflow-node trigger-node
      min-w-[180px] rounded-lg border-2 p-3
      ${selected ? 'border-blue-500 shadow-lg shadow-blue-100' : 'border-blue-300'}
      ${data.isConfigured ? 'bg-blue-50' : 'bg-white'}
    `}>
      <div className="flex items-center gap-2 mb-1">
        <div className="w-6 h-6 rounded-full bg-blue-500 flex items-center justify-center">
          <Zap className="w-3 h-3 text-white" />
        </div>
        <span className="text-xs font-semibold text-blue-700 uppercase tracking-wide">Trigger</span>
      </div>
      
      <div className="font-medium text-sm text-gray-900">{label}</div>
      
      {configuredEvent && (
        <div className="mt-1 text-xs text-gray-500 bg-white rounded px-2 py-1">
          {configuredEvent}
        </div>
      )}
      
      {!data.isConfigured && (
        <div className="mt-1 text-xs text-orange-500">⚠ Chưa cấu hình</div>
      )}
      
      {/* Output handle — kết nối đến action nodes */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="w-3 h-3 bg-blue-500 border-2 border-white"
      />
    </div>
  );
}
```

**`frontend/src/components/workflow/nodes/ActionNode.tsx`**

```tsx
import React from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { Play, CheckCircle, XCircle } from 'lucide-react';
import type { WorkflowNodeData } from '../../../types/workflow';

const ACTION_ICONS: Record<string, string> = {
  'action.create_note': '📝',
  'action.send_notification': '🔔',
  'action.call_ai': '🤖',
  'action.create_schedule': '📅',
  'action.call_webhook': '🌐',
};

export function ActionNode({ data, selected }: NodeProps<WorkflowNodeData>) {
  const icon = ACTION_ICONS[data.nodeType] || '⚡';
  
  return (
    <div className={`
      workflow-node action-node
      min-w-[180px] rounded-lg border-2 p-3
      ${selected ? 'border-purple-500 shadow-lg shadow-purple-100' : 'border-purple-300'}
      ${data.isConfigured ? 'bg-purple-50' : 'bg-white'}
    `}>
      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-purple-500 border-2 border-white"
      />
      
      <div className="flex items-center gap-2 mb-1">
        <span className="text-lg">{icon}</span>
        <span className="text-xs font-semibold text-purple-700 uppercase tracking-wide">Action</span>
      </div>
      
      <div className="font-medium text-sm text-gray-900">{data.label}</div>
      
      {!data.isConfigured && (
        <div className="mt-1 text-xs text-orange-500">⚠ Chưa cấu hình</div>
      )}
      
      {/* Output handle — cho chaining actions */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="w-3 h-3 bg-purple-500 border-2 border-white"
      />
    </div>
  );
}
```

**`frontend/src/components/workflow/nodes/index.ts`**

```typescript
import { TriggerNode } from './TriggerNode';
import { ActionNode } from './ActionNode';

export const nodeTypes = {
  triggerNode: TriggerNode,
  actionNode: ActionNode,
};
```

---

## 7. Node Palette (Drag Source)

**`frontend/src/components/workflow/NodePalette.tsx`**

```tsx
import React from 'react';
import { useWorkflowStore } from '../../stores/workflowStore';

interface PaletteItem {
  nodeType: string;
  label: string;
  description: string;
  category: 'trigger' | 'action';
}

function PaletteNode({ item }: { item: PaletteItem }) {
  const handleDragStart = (e: React.DragEvent) => {
    e.dataTransfer.setData('application/workflow-node', JSON.stringify(item));
    e.dataTransfer.effectAllowed = 'move';
  };
  
  return (
    <div
      draggable
      onDragStart={handleDragStart}
      className={`
        cursor-grab active:cursor-grabbing
        flex items-center gap-2 p-2 rounded-lg border
        hover:shadow-sm transition-shadow
        ${item.category === 'trigger'
          ? 'bg-blue-50 border-blue-200 hover:border-blue-400'
          : 'bg-purple-50 border-purple-200 hover:border-purple-400'
        }
      `}
    >
      <div className="flex-1">
        <div className="text-sm font-medium text-gray-900">{item.label}</div>
        <div className="text-xs text-gray-500">{item.description}</div>
      </div>
    </div>
  );
}

export function NodePalette() {
  const { availableActions, availableTriggers } = useWorkflowStore();
  
  const triggerItems: PaletteItem[] = availableTriggers.map(t => ({
    nodeType: t.type,
    label: t.display_name,
    description: t.description,
    category: 'trigger',
  }));
  
  const actionItems: PaletteItem[] = availableActions.map(a => ({
    nodeType: a.type,
    label: a.display_name,
    description: a.description,
    category: 'action',
  }));
  
  return (
    <div className="w-64 bg-white border-r border-gray-200 flex flex-col h-full overflow-hidden">
      <div className="p-3 border-b border-gray-200">
        <h3 className="font-semibold text-gray-900 text-sm">Components</h3>
        <p className="text-xs text-gray-500 mt-0.5">Kéo thả vào canvas</p>
      </div>
      
      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {/* Triggers */}
        <div>
          <div className="text-xs font-semibold text-blue-600 uppercase tracking-wider mb-2">
            Triggers
          </div>
          <div className="space-y-1.5">
            {triggerItems.map(item => (
              <PaletteNode key={item.nodeType} item={item} />
            ))}
          </div>
        </div>
        
        {/* Actions */}
        <div>
          <div className="text-xs font-semibold text-purple-600 uppercase tracking-wider mb-2">
            Actions
          </div>
          <div className="space-y-1.5">
            {actionItems.map(item => (
              <PaletteNode key={item.nodeType} item={item} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
```

---

## 8. Main Canvas

**`frontend/src/components/workflow/WorkflowCanvas.tsx`**

```tsx
import React, { useCallback, useRef } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { nodeTypes } from './nodes';
import { useWorkflowStore } from '../../stores/workflowStore';
import type { WorkflowNode, WorkflowNodeData } from '../../types/workflow';

export function WorkflowCanvas() {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const {
    nodes, edges,
    onNodesChange, onEdgesChange, onConnect,
    addNode, selectNode,
  } = useWorkflowStore();
  
  const onDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    
    const paletteData = event.dataTransfer.getData('application/workflow-node');
    if (!paletteData || !reactFlowWrapper.current) return;
    
    const item = JSON.parse(paletteData);
    
    // Calculate drop position relative to canvas
    const rect = reactFlowWrapper.current.getBoundingClientRect();
    const position = {
      x: event.clientX - rect.left - 90,
      y: event.clientY - rect.top - 40,
    };
    
    const newNode: WorkflowNode = {
      id: `node-${Date.now()}`,
      type: item.category === 'trigger' ? 'triggerNode' : 'actionNode',
      position,
      data: {
        label: item.label,
        nodeType: item.nodeType,
        config: {},
        isConfigured: false,
      } as WorkflowNodeData,
    };
    
    addNode(newNode);
  }, [addNode]);
  
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);
  
  const onNodeClick = useCallback((_: React.MouseEvent, node: any) => {
    selectNode(node.id);
  }, [selectNode]);
  
  const onPaneClick = useCallback(() => {
    selectNode(null);
  }, [selectNode]);
  
  return (
    <div ref={reactFlowWrapper} className="flex-1 h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        fitView
        deleteKeyCode="Delete"
        className="bg-gray-50"
      >
        <Background variant={BackgroundVariant.Dots} gap={20} color="#e5e7eb" />
        <Controls />
        <MiniMap
          nodeColor={(node) =>
            node.type === 'triggerNode' ? '#3b82f6' : '#8b5cf6'
          }
          className="bg-white border border-gray-200 rounded"
        />
      </ReactFlow>
    </div>
  );
}
```

---

## 9. Config Panel (Right Sidebar)

**`frontend/src/components/workflow/ConfigPanel.tsx`**

```tsx
import React from 'react';
import { useWorkflowStore } from '../../stores/workflowStore';
import { TriggerConfigPanel } from './panels/TriggerConfigPanel';
import { ActionConfigPanel } from './panels/ActionConfigPanel';
import { X } from 'lucide-react';

export function ConfigPanel() {
  const { nodes, selectedNodeId, selectNode } = useWorkflowStore();
  
  if (!selectedNodeId) {
    return (
      <div className="w-72 bg-white border-l border-gray-200 flex items-center justify-center">
        <div className="text-center text-gray-400 px-4">
          <div className="text-3xl mb-2">👆</div>
          <div className="text-sm">Chọn một node để cấu hình</div>
        </div>
      </div>
    );
  }
  
  const selectedNode = nodes.find(n => n.id === selectedNodeId);
  if (!selectedNode) return null;
  
  const isTrigger = selectedNode.type === 'triggerNode';
  
  return (
    <div className="w-72 bg-white border-l border-gray-200 flex flex-col h-full">
      <div className="flex items-center justify-between p-3 border-b border-gray-200">
        <h3 className="font-semibold text-gray-900 text-sm">
          {isTrigger ? 'Cấu hình Trigger' : 'Cấu hình Action'}
        </h3>
        <button
          onClick={() => selectNode(null)}
          className="p-1 hover:bg-gray-100 rounded"
        >
          <X className="w-4 h-4 text-gray-500" />
        </button>
      </div>
      
      <div className="flex-1 overflow-y-auto p-3">
        {isTrigger ? (
          <TriggerConfigPanel node={selectedNode} />
        ) : (
          <ActionConfigPanel node={selectedNode} />
        )}
      </div>
    </div>
  );
}
```

**`frontend/src/components/workflow/panels/TriggerConfigPanel.tsx`**

```tsx
import React from 'react';
import { useWorkflowStore } from '../../../stores/workflowStore';
import type { WorkflowNode } from '../../../types/workflow';

const INTERNAL_EVENTS = [
  { value: 'note.created', label: 'Note được tạo' },
  { value: 'note.updated', label: 'Note được cập nhật' },
  { value: 'note.deleted', label: 'Note bị xóa' },
  { value: 'schedule.created', label: 'Lịch được tạo' },
  { value: 'schedule.updated', label: 'Lịch được cập nhật' },
  { value: 'schedule.completed', label: 'Lịch hoàn thành' },
  { value: 'asset.uploaded', label: 'File được upload' },
  { value: 'asset.processed', label: 'File được xử lý xong' },
];

interface Props { node: WorkflowNode; }

export function TriggerConfigPanel({ node }: Props) {
  const { updateNodeConfig } = useWorkflowStore();
  const config = node.data.config as { event?: string; filters?: Record<string, string> };
  
  if (node.data.nodeType === 'trigger.internal_event') {
    return (
      <div className="space-y-3">
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">
            Loại sự kiện *
          </label>
          <select
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={config.event || ''}
            onChange={(e) => updateNodeConfig(node.id, { ...config, event: e.target.value })}
          >
            <option value="">Chọn sự kiện...</option>
            {INTERNAL_EVENTS.map(ev => (
              <option key={ev.value} value={ev.value}>{ev.label}</option>
            ))}
          </select>
        </div>
        
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">
            Workspace ID (tùy chọn)
          </label>
          <input
            type="text"
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Lọc theo workspace..."
            value={config.filters?.workspace_id || ''}
            onChange={(e) => updateNodeConfig(node.id, {
              ...config,
              filters: { ...config.filters, workspace_id: e.target.value }
            })}
          />
        </div>
      </div>
    );
  }
  
  if (node.data.nodeType === 'trigger.webhook') {
    return (
      <div className="space-y-3">
        <div className="bg-blue-50 rounded-lg p-3 text-sm text-blue-800">
          <div className="font-medium mb-1">Webhook URL</div>
          <div className="text-xs text-blue-600">
            Sẽ được tạo tự động khi workflow được lưu lần đầu
          </div>
        </div>
      </div>
    );
  }
  
  if (node.data.nodeType === 'trigger.manual') {
    return (
      <div className="bg-gray-50 rounded-lg p-3 text-sm text-gray-600">
        Workflow sẽ chạy khi user bấm nút "Run" thủ công.
        Không cần cấu hình thêm.
      </div>
    );
  }
  
  return <div className="text-sm text-gray-500">Không có config</div>;
}
```

---

## 10. Workflow Builder Page

**`frontend/src/pages/workflows/[id]/builder.tsx`**

```tsx
import React, { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { NodePalette } from '../../../components/workflow/NodePalette';
import { WorkflowCanvas } from '../../../components/workflow/WorkflowCanvas';
import { ConfigPanel } from '../../../components/workflow/ConfigPanel';
import { WorkflowToolbar } from '../../../components/workflow/WorkflowToolbar';
import { useWorkflowStore } from '../../../stores/workflowStore';
import { useWorkflowApi } from '../../../hooks/workflow/useWorkflowApi';

export function WorkflowBuilderPage() {
  const { id } = useParams<{ id: string }>();
  const { setWorkflow, setAvailableActions } = useWorkflowStore();
  const { fetchWorkflow, fetchActions } = useWorkflowApi();
  
  useEffect(() => {
    if (!id) return;
    
    // Load workflow definition
    fetchWorkflow(id).then(workflow => {
      if (workflow) setWorkflow(workflow);
    });
    
    // Load available actions/triggers từ API
    fetchActions().then(data => {
      if (data) setAvailableActions(data.actions, data.triggers);
    });
  }, [id]);
  
  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* Toolbar */}
      <WorkflowToolbar />
      
      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Node Palette */}
        <NodePalette />
        
        {/* Center: React Flow Canvas */}
        <WorkflowCanvas />
        
        {/* Right: Config Panel */}
        <ConfigPanel />
      </div>
    </div>
  );
}
```

---

## 11. Toolbar với Save + Activate

**`frontend/src/components/workflow/WorkflowToolbar.tsx`**

```tsx
import React from 'react';
import { Save, Play, Pause, ArrowLeft, History } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useWorkflowStore } from '../../stores/workflowStore';
import { useWorkflowApi } from '../../hooks/workflow/useWorkflowApi';

export function WorkflowToolbar() {
  const navigate = useNavigate();
  const { workflow, nodes, edges, isDirty, isSaving, markSaved, setIsSaving } = useWorkflowStore();
  const { saveWorkflow, activateWorkflow, pauseWorkflow, triggerManual } = useWorkflowApi();
  
  const handleSave = async () => {
    if (!workflow) return;
    setIsSaving(true);
    
    await saveWorkflow(workflow.id, { nodes, edges, variables: {} });
    markSaved();
    setIsSaving(false);
  };
  
  const handleActivate = async () => {
    if (!workflow) return;
    if (isDirty) await handleSave();
    await activateWorkflow(workflow.id);
  };
  
  const handlePause = async () => {
    if (!workflow) return;
    await pauseWorkflow(workflow.id);
  };
  
  const handleManualRun = async () => {
    if (!workflow) return;
    await triggerManual(workflow.id, {});
  };
  
  const isActive = workflow?.status === 'active';
  
  return (
    <div className="h-12 bg-white border-b border-gray-200 flex items-center px-4 gap-3">
      {/* Back */}
      <button
        onClick={() => navigate('/workflows')}
        className="flex items-center gap-1.5 text-gray-600 hover:text-gray-900 text-sm"
      >
        <ArrowLeft className="w-4 h-4" />
        Workflows
      </button>
      
      <div className="h-4 w-px bg-gray-200" />
      
      {/* Workflow name */}
      <span className="font-medium text-gray-900 text-sm flex-1">
        {workflow?.name || 'Untitled Workflow'}
      </span>
      
      {/* Status badge */}
      {workflow && (
        <span className={`
          text-xs px-2 py-0.5 rounded-full font-medium
          ${isActive ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}
        `}>
          {workflow.status}
        </span>
      )}
      
      {isDirty && <span className="text-xs text-orange-500">● Chưa lưu</span>}
      
      <div className="flex items-center gap-2">
        {/* Save */}
        <button
          onClick={handleSave}
          disabled={!isDirty || isSaving}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50"
        >
          <Save className="w-3.5 h-3.5" />
          {isSaving ? 'Đang lưu...' : 'Lưu'}
        </button>
        
        {/* Activate / Pause */}
        {!isActive ? (
          <button
            onClick={handleActivate}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700"
          >
            <Play className="w-3.5 h-3.5" />
            Activate
          </button>
        ) : (
          <button
            onClick={handlePause}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-yellow-500 text-white rounded-lg hover:bg-yellow-600"
          >
            <Pause className="w-3.5 h-3.5" />
            Pause
          </button>
        )}
        
        {/* Manual run */}
        {isActive && (
          <button
            onClick={handleManualRun}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            <Play className="w-3.5 h-3.5" />
            Run Now
          </button>
        )}
        
        {/* History */}
        <button
          onClick={() => navigate(`/workflows/${workflow?.id}/executions`)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-50"
        >
          <History className="w-3.5 h-3.5" />
          History
        </button>
      </div>
    </div>
  );
}
```

---

## 12. Thêm Routes vào Cortex Router

Trong file routing của Cortex (`App.tsx` hoặc router config), thêm:

```tsx
// Thêm vào router
import { WorkflowListPage } from './pages/workflows';
import { WorkflowBuilderPage } from './pages/workflows/[id]/builder';
import { WorkflowExecutionsPage } from './pages/workflows/[id]/executions';

// Routes
<Route path="/workflows" element={<WorkflowListPage />} />
<Route path="/workflows/new" element={<WorkflowBuilderPage />} />
<Route path="/workflows/:id/builder" element={<WorkflowBuilderPage />} />
<Route path="/workflows/:id/executions" element={<WorkflowExecutionsPage />} />
```

Thêm vào sidebar của Cortex:

```tsx
// Trong sidebar navigation
{ path: '/workflows', icon: <Workflow />, label: 'Workflows' }
```

---

## 13. Verification Checklist — Cuối Phase 4

- [ ] `/workflows` hiện danh sách workflows có phân trang
- [ ] "Tạo mới" mở builder với canvas trống
- [ ] Kéo Trigger node từ palette thả vào canvas → node xuất hiện
- [ ] Kéo Action node từ palette thả vào canvas → node xuất hiện
- [ ] Click node → Config panel mở bên phải
- [ ] Chọn event trong TriggerConfigPanel → config được lưu vào node data
- [ ] Kéo từ output handle của Trigger đến input handle của Action → edge xuất hiện
- [ ] Nút "Lưu" gọi API PATCH, nhận 200, "● Chưa lưu" biến mất
- [ ] Nút "Activate" gọi API activate, status badge chuyển sang "active"
- [ ] Reload trang → workflow load lại đúng nodes + edges
- [ ] `/workflows/:id/executions` hiện execution history
