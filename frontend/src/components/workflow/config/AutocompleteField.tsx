import { useCallback, useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react'

export type TemplateVar = {
  label: string
  value: string
}

type Props = {
  value: string
  onChange: (value: string) => void
  variables: TemplateVar[]
  placeholder?: string
  multiline?: boolean
}

export function AutocompleteField({ value, onChange, variables, placeholder, multiline }: Props) {
  const ref = useRef<HTMLTextAreaElement | HTMLInputElement>(null)
  const [acState, setAcState] = useState<{ start: number } | null>(null)
  const [activeIdx, setActiveIdx] = useState(0)
  const [measuredOffset, setMeasuredOffset] = useState<{ top: number; left: number } | null>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const measureCursor = useCallback((el: HTMLTextAreaElement | HTMLInputElement) => {
    const pos = el.selectionStart ?? 0
    const before = el.value.slice(0, pos)
    const mirror = document.createElement('div')
    const cs = window.getComputedStyle(el)

    mirror.style.cssText = cs.cssText
    mirror.style.position = 'absolute'
    mirror.style.top = '0'
    mirror.style.left = '0'
    mirror.style.visibility = 'hidden'
    mirror.style.whiteSpace = 'pre-wrap'
    mirror.style.wordWrap = 'break-word'
    mirror.style.width = el.offsetWidth + 'px'
    mirror.style.height = 'auto'
    mirror.style.overflow = 'hidden'
    mirror.style.pointerEvents = 'none'

    mirror.textContent = before
    const marker = document.createElement('span')
    marker.textContent = '|'
    mirror.appendChild(marker)

    el.parentElement!.appendChild(mirror)
    const markerRect = marker.getBoundingClientRect()
    const elRect = el.getBoundingClientRect()
    el.parentElement!.removeChild(mirror)

    return { top: markerRect.top - elRect.top, left: markerRect.left - elRect.left }
  }, [])

  const check = useCallback((el: HTMLTextAreaElement | HTMLInputElement) => {
    const pos = el.selectionStart ?? 0
    const before = el.value.slice(0, pos)
    const lastOpen = before.lastIndexOf('{{')
    if (lastOpen !== -1) {
      const afterOpen = before.slice(lastOpen + 2)
      if (!afterOpen.includes('}}')) {
        setAcState({ start: lastOpen })
        setActiveIdx(0)
        setMeasuredOffset(measureCursor(el))
        return
      }
    }
    setAcState(null)
    setMeasuredOffset(null)
  }, [measureCursor])

  useEffect(() => {
    if (acState && ref.current) {
      setMeasuredOffset(measureCursor(ref.current))
    }
  }, [acState, measureCursor])

  const insertVar = useCallback((variable: string) => {
    const el = ref.current
    if (!el) return
    const pos = el.selectionStart ?? 0
    const before = el.value.slice(0, pos)
    const lastOpen = before.lastIndexOf('{{')
    if (lastOpen === -1) return

    const newVal = el.value.slice(0, lastOpen) + variable + el.value.slice(pos)
    onChange(newVal)
    setAcState(null)
    setMeasuredOffset(null)

    requestAnimationFrame(() => {
      el.focus()
      const newPos = lastOpen + variable.length
      el.setSelectionRange(newPos, newPos)
    })
  }, [onChange])

  const cursorFilter = (() => {
    if (!acState || !ref.current) return ''
    const pos = ref.current.selectionStart ?? 0
    const before = ref.current.value.slice(0, pos)
    const lastOpen = before.lastIndexOf('{{')
    if (lastOpen === -1) return ''
    return before.slice(lastOpen + 2)
  })()

  const filtered = cursorFilter
    ? variables.filter(v => v.value.toLowerCase().includes(cursorFilter.toLowerCase()))
    : variables

  const handleChange = (e: ChangeEvent<HTMLTextAreaElement | HTMLInputElement>) => {
    onChange(e.target.value)
    check(e.target)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement | HTMLInputElement>) => {
    if (acState && filtered.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActiveIdx(i => Math.min(i + 1, filtered.length - 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActiveIdx(i => Math.max(i - 1, 0))
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        if (filtered[activeIdx]) {
          e.preventDefault()
          insertVar(filtered[activeIdx].value)
          return
        }
      } else if (e.key === 'Escape') {
        setAcState(null)
        setMeasuredOffset(null)
        return
      }
    }
    if (e.key === 'Tab' && !acState) {
      return
    }
  }

  useEffect(() => {
    if (!acState) return
    const handler = (e: MouseEvent) => {
      if (
        ref.current && !ref.current.contains(e.target as Node) &&
        dropdownRef.current && !dropdownRef.current.contains(e.target as Node)
      ) {
        setAcState(null)
        setMeasuredOffset(null)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [acState])

  const handleClick = () => {
    if (ref.current) check(ref.current)
  }

  const showDropdown = acState && filtered.length > 0

  const dropdownStyle: React.CSSProperties = {
    position: 'absolute',
    top: measuredOffset !== null ? measuredOffset.top + 20 : '100%',
    left: measuredOffset !== null ? measuredOffset.left : 0,
    right: 'auto',
    zIndex: 9999,
    minWidth: '220px',
  }

  const renderDropdown = () => {
    if (!showDropdown) return null
    return (
      <div ref={dropdownRef} className="wf-autocomplete-dropdown" style={dropdownStyle}>
        {filtered.map((v, i) => (
          <button
            key={v.value}
            type="button"
            className={`wf-autocomplete-item ${i === activeIdx ? 'active' : ''}`}
            onClick={() => insertVar(v.value)}
            onMouseDown={e => e.preventDefault()}
            ref={i === activeIdx ? el => el?.scrollIntoView({ block: 'nearest' }) : undefined}
          >
            <span className="wf-autocomplete-value">{v.value}</span>
            {v.label && <span className="wf-autocomplete-label">{v.label}</span>}
          </button>
        ))}
      </div>
    )
  }

  const cls = multiline ? 'wf-config-textarea' : 'wf-config-input'

  if (multiline) {
    return (
      <div style={{ position: 'relative', flex: 1 }}>
        <textarea
          ref={ref as React.RefObject<HTMLTextAreaElement>}
          className={cls}
          style={{ width: '100%' }}
          rows={4}
          value={value}
          placeholder={placeholder}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onClick={handleClick}
        />
        {renderDropdown()}
      </div>
    )
  }

  return (
    <div style={{ position: 'relative', flex: 1 }}>
      <input
        ref={ref as React.RefObject<HTMLInputElement>}
        className={cls}
        style={{ width: '100%' }}
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onClick={handleClick}
      />
      {renderDropdown()}
    </div>
  )
}
