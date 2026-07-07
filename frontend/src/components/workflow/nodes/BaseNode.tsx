import { memo } from 'react'
import { Handle, Position, type NodeProps } from 'reactflow'
import { motion } from 'framer-motion'
import { AlertTriangle, Play, Power, Trash2, MoreHorizontal } from 'lucide-react'
import { cn } from '../../../lib/utils'
import { getNodeConfig } from '../nodeConfig'

type BaseNodeData = {
  label: string
  config?: Record<string, unknown>
  isConfigured?: boolean
}

type BaseNodeWrapperProps = NodeProps<BaseNodeData> & {
  hasInput?: boolean
  hasOutput?: boolean
  isCondition?: boolean
  isTrigger?: boolean
  children?: React.ReactNode
}

export const BaseNode = memo(function BaseNode({
  type,
  data,
  selected,
  hasInput = true,
  hasOutput = true,
  isCondition = false,
  isTrigger = false,
  children,
}: BaseNodeWrapperProps) {
  const config = getNodeConfig(type)
  const color = config?.color ?? 'var(--text-tertiary)'
  const Icon = config?.icon

  const handleExecute = (e: React.MouseEvent) => {
    e.stopPropagation()
    e.preventDefault()
    const fn = (data as Record<string, unknown>).onExecute as ((config: Record<string, unknown>) => void) | undefined
    if (fn) {
      fn((data.config as Record<string, unknown>) ?? {})
    }
  }

  return (
    <motion.div
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      exit={{ scale: 0.8, opacity: 0 }}
      transition={{ type: 'spring', stiffness: 500, damping: 30 }}
      className={cn(
        'wf-node',
        selected && 'wf-node--selected',
        isTrigger && 'wf-node--trigger',
        isCondition && 'wf-node--condition'
      )}
      style={{ '--node-color': color } as React.CSSProperties}
    >
      {hasInput && (
        <Handle
          type="target"
          position={Position.Left}
          className="wf-handle"
        />
      )}

      {isCondition && (
        <>
          <Handle
            type="source"
            position={Position.Top}
            id="true"
            className="wf-handle wf-handle--true"
          />
          <span className="wf-handle-label wf-handle-label--true">True</span>
          <Handle
            type="source"
            position={Position.Bottom}
            id="false"
            className="wf-handle wf-handle--false"
          />
          <span className="wf-handle-label wf-handle-label--false">False</span>
        </>
      )}

      {hasOutput && !isCondition && (
        <Handle
          type="source"
          position={Position.Right}
          className="wf-handle"
        />
      )}

      <div className="wf-node-toolbar">
        <button type="button" className="wf-node-toolbar-btn" title="Execute step" onClick={handleExecute}>
          <Play size={12} />
        </button>
        <button type="button" className="wf-node-toolbar-btn" title="Deactivate">
          <Power size={12} />
        </button>
        <button type="button" className="wf-node-toolbar-btn" title="Delete">
          <Trash2 size={12} />
        </button>
        <button type="button" className="wf-node-toolbar-btn" title="More">
          <MoreHorizontal size={12} />
        </button>
      </div>

      <div className="wf-node-body">
        <div className="wf-node-icon-wrap">
          {Icon && <Icon size={22} />}
        </div>
        <div className="wf-node-info">
          <div className="wf-node-label">{data.label}</div>
          {data.isConfigured === false && (
            <span className="wf-node-badge" title="Not configured">
              <AlertTriangle size={11} />
            </span>
          )}
        </div>
        {children && <div className="wf-node-children">{children}</div>}
      </div>
    </motion.div>
  )
})
