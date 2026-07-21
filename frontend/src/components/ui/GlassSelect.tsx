import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'

import styles from './GlassSelect.module.css'

export interface GlassSelectOption {
  value: string
  label: ReactNode
  disabled?: boolean
}

export interface GlassSelectProps {
  /** Visible field label. Omit for compact controls (use aria-label). */
  label?: string
  value: string
  options: GlassSelectOption[]
  onChange: (value: string) => void
  className?: string
  disabled?: boolean
  id?: string
  /** Accessible name when `label` is omitted. */
  'aria-label'?: string
  /** Visual density / shape. */
  size?: 'default' | 'compact' | 'pill'
  /** Prefer opening upward when space is tight (still auto-flips if needed). */
  placement?: 'bottom' | 'top'
  /** Stretch trigger to container width (default true). */
  fullWidth?: boolean
}

interface MenuCoords {
  top: number
  left: number
  width: number
  maxHeight: number
  openUp: boolean
}

export function GlassSelect({
  label,
  value,
  options,
  onChange,
  className = '',
  disabled = false,
  id,
  'aria-label': ariaLabel,
  size = 'default',
  placement = 'bottom',
  fullWidth = true,
}: GlassSelectProps) {
  const reactId = useId()
  const listboxId = `${reactId}-listbox`
  const labelId = label ? `${reactId}-label` : undefined
  const triggerId = id ?? `${reactId}-trigger`

  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(-1)
  const [coords, setCoords] = useState<MenuCoords | null>(null)

  const selectedIndex = useMemo(
    () => options.findIndex((option) => option.value === value),
    [options, value],
  )
  const selected = selectedIndex >= 0 ? options[selectedIndex] : undefined

  const enabledIndexes = useMemo(
    () =>
      options
        .map((option, index) => (option.disabled ? -1 : index))
        .filter((index) => index >= 0),
    [options],
  )

  const measure = useCallback(() => {
    const trigger = triggerRef.current
    if (!trigger) return null

    const rect = trigger.getBoundingClientRect()
    const gap = 6
    const preferredHeight = Math.min(options.length * 44 + 16, 280)
    const spaceBelow = window.innerHeight - rect.bottom - gap
    const spaceAbove = rect.top - gap

    let openUp = placement === 'top'
    if (placement === 'top') {
      openUp = spaceAbove >= preferredHeight || spaceAbove > spaceBelow
    } else {
      openUp = spaceBelow < preferredHeight && spaceAbove > spaceBelow
    }

    const available = openUp ? spaceAbove : spaceBelow
    const maxHeight = Math.max(120, Math.min(preferredHeight, available))

    return {
      top: openUp ? rect.top - gap : rect.bottom + gap,
      left: rect.left,
      width: rect.width,
      maxHeight,
      openUp,
    } satisfies MenuCoords
  }, [options.length, placement])

  const close = useCallback(() => {
    setOpen(false)
    setHighlight(-1)
    setCoords(null)
  }, [])

  const openMenu = useCallback(() => {
    if (disabled || options.length === 0) return

    const next = measure()
    if (next) setCoords(next)

    const start =
      selectedIndex >= 0 && !options[selectedIndex]?.disabled
        ? selectedIndex
        : (enabledIndexes[0] ?? -1)
    setHighlight(start)
    setOpen(true)
  }, [disabled, enabledIndexes, measure, options, selectedIndex])

  const toggle = useCallback(() => {
    if (open) close()
    else openMenu()
  }, [close, open, openMenu])

  const commit = useCallback(
    (index: number) => {
      const option = options[index]
      if (!option || option.disabled) return
      onChange(option.value)
      close()
      requestAnimationFrame(() => {
        document.getElementById(triggerId)?.focus()
      })
    },
    [close, onChange, options, triggerId],
  )

  const moveHighlight = useCallback(
    (delta: number) => {
      if (enabledIndexes.length === 0) return
      setHighlight((current) => {
        const pos = enabledIndexes.indexOf(current)
        const nextPos =
          pos === -1
            ? delta > 0
              ? 0
              : enabledIndexes.length - 1
            : (pos + delta + enabledIndexes.length) % enabledIndexes.length
        return enabledIndexes[nextPos] ?? enabledIndexes[0]
      })
    },
    [enabledIndexes],
  )

  useLayoutEffect(() => {
    if (!open) return

    function update() {
      const next = measure()
      if (next) setCoords(next)
    }

    update()
    window.addEventListener('resize', update)
    // Capture scroll on any ancestor so fixed menus track the trigger.
    window.addEventListener('scroll', update, true)
    return () => {
      window.removeEventListener('resize', update)
      window.removeEventListener('scroll', update, true)
    }
  }, [measure, open])

  useEffect(() => {
    if (!open) return

    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node
      if (rootRef.current?.contains(target) || listRef.current?.contains(target)) return
      close()
    }

    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        close()
        document.getElementById(triggerId)?.focus()
      }
    }

    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [close, open, triggerId])

  useEffect(() => {
    if (!open || highlight < 0) return
    const item = listRef.current?.querySelector<HTMLElement>(`[data-index="${highlight}"]`)
    item?.scrollIntoView({ block: 'nearest' })
  }, [highlight, open])

  function onTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>): void {
    if (disabled) return

    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        if (!open) openMenu()
        else moveHighlight(1)
        break
      case 'ArrowUp':
        event.preventDefault()
        if (!open) openMenu()
        else moveHighlight(-1)
        break
      case 'Enter':
      case ' ':
        event.preventDefault()
        if (!open) openMenu()
        else if (highlight >= 0) commit(highlight)
        break
      case 'Home':
        if (open && enabledIndexes.length) {
          event.preventDefault()
          setHighlight(enabledIndexes[0])
        }
        break
      case 'End':
        if (open && enabledIndexes.length) {
          event.preventDefault()
          setHighlight(enabledIndexes[enabledIndexes.length - 1])
        }
        break
      case 'Escape':
        if (open) {
          event.preventDefault()
          close()
        }
        break
      default:
        break
    }
  }

  const rootClass = [
    styles.root,
    fullWidth ? styles.fullWidth : styles.autoWidth,
    className,
  ]
    .filter(Boolean)
    .join(' ')

  const triggerClass = [
    styles.trigger,
    styles[size],
    'glass-lens',
    open ? styles.triggerOpen : '',
    disabled ? styles.triggerDisabled : '',
  ]
    .filter(Boolean)
    .join(' ')

  const menuStyle: CSSProperties | undefined = coords
    ? {
        top: coords.openUp ? undefined : coords.top,
        bottom: coords.openUp ? window.innerHeight - coords.top : undefined,
        left: coords.left,
        width: coords.width,
        maxHeight: coords.maxHeight,
      }
    : undefined

  const menu = open && coords
    ? createPortal(
        <ul
          ref={listRef}
          id={listboxId}
          className={`${styles.menu} ${styles.menuOpen} ${coords.openUp ? styles.menuUp : styles.menuDown}`}
          role="listbox"
          aria-labelledby={labelId}
          aria-activedescendant={highlight >= 0 ? `${reactId}-opt-${highlight}` : undefined}
          style={menuStyle}
        >
          {options.map((option, index) => {
            const isSelected = option.value === value
            const isActive = index === highlight
            const optionClass = [
              styles.option,
              isSelected ? styles.optionSelected : '',
              isActive ? styles.optionActive : '',
              option.disabled ? styles.optionDisabled : '',
            ]
              .filter(Boolean)
              .join(' ')

            return (
              <li
                key={`${option.value}::${index}`}
                id={`${reactId}-opt-${index}`}
                role="option"
                data-index={index}
                className={optionClass}
                aria-selected={isSelected}
                aria-disabled={option.disabled || undefined}
                onMouseEnter={() => {
                  if (!option.disabled) setHighlight(index)
                }}
                onMouseDown={(event) => {
                  event.preventDefault()
                }}
                onClick={() => {
                  if (!option.disabled) commit(index)
                }}
              >
                <span className={styles.optionLabel}>{option.label}</span>
                {isSelected ? (
                  <span className={styles.check} aria-hidden="true">
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <path
                        d="M2.5 7.2L5.4 10.1L11.5 3.8"
                        stroke="currentColor"
                        strokeWidth="1.7"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </span>
                ) : null}
              </li>
            )
          })}
        </ul>,
        document.body,
      )
    : null

  return (
    <div className={rootClass} ref={rootRef}>
      {label ? (
        <span className={styles.label} id={labelId}>
          {label}
        </span>
      ) : null}

      <div className={styles.control}>
        <button
          ref={triggerRef}
          type="button"
          id={triggerId}
          className={triggerClass}
          disabled={disabled}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-labelledby={labelId}
          aria-label={label ? undefined : ariaLabel}
          onClick={toggle}
          onKeyDown={onTriggerKeyDown}
        >
          <span className={styles.value}>{selected?.label ?? value}</span>
          <span className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`} aria-hidden="true">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path
                d="M2.5 4.25L6 7.75L9.5 4.25"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
        </button>
      </div>

      {menu}
    </div>
  )
}
