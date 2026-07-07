import { forwardRef, type Ref } from 'react'
import ReactFlow, {
  Controls,
  Background,
  MiniMap,
  BackgroundVariant,
  type ReactFlowProps,
  type ReactFlowInstance,
  type DefaultEdgeOptions,
} from 'reactflow'
import { cn } from '../../lib/utils'
import { getNodeColor } from './nodeConfig'

const defaultEdgeOptions: DefaultEdgeOptions = {
  type: 'smoothstep',
  animated: true,
  style: { stroke: 'var(--wf-edge)', strokeWidth: 2 },
}

const connectionLineStyle = {
  stroke: 'var(--wf-edge-active)',
  strokeWidth: 2,
}

type WorkflowCanvasProps = ReactFlowProps & {
  reactFlowWrapperRef?: Ref<HTMLDivElement>
}

export const WorkflowCanvas = forwardRef<ReactFlowInstance, WorkflowCanvasProps>(
  function WorkflowCanvas({ className, children, reactFlowWrapperRef, ...props }, ref) {
    return (
      <div className={cn('wf-canvas', className)} ref={reactFlowWrapperRef}>
        <ReactFlow
          ref={ref as Ref<HTMLDivElement>}
          fitView
          deleteKeyCode={['Backspace', 'Delete']}
          selectionOnDrag
          panOnDrag={[1, 2]}
          defaultEdgeOptions={defaultEdgeOptions}
          connectionLineStyle={connectionLineStyle}
          connectionRadius={20}
          {...props}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={20}
            size={1}
          />
          <Controls
            className="wf-controls"
          />
          <MiniMap
            nodeStrokeColor="var(--wf-panel-border)"
            nodeColor={n => getNodeColor(n.type ?? '')}
            maskColor="rgba(0,0,0,0.6)"
            className="wf-minimap"
          />
          {children}
        </ReactFlow>
      </div>
    )
  }
)
