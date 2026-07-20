import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react'

import {
  createPlanogram,
  deletePlanogram,
  listPlanograms,
  setActivePlanogram,
  updatePlanogram,
} from '@/api/planogram'
import type { Language, UI_TEXT } from '@/lib/i18n'
import type { Planogram, PlanogramSlot } from '@/types/planogram'

import styles from './PlanogramPanel.module.css'

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
const MIN_SLOT_SIZE = 0.01
const PASTE_GAP = 0.01
const PASTE_FALLBACK_NUDGE = 0.03

interface PlanogramPanelProps {
  text: (typeof UI_TEXT)[Language]['planogram']
  /** When false the current user is read-only (staff): hide create/edit/delete/activate. */
  canWrite?: boolean
  readOnlyNotice?: string
}

interface DraftState {
  id: string | null
  name: string
  description: string
  imageBase64: string
  imageWidth: number
  imageHeight: number
  slots: PlanogramSlot[]
}

interface DrawState {
  startX: number
  startY: number
  currentX: number
  currentY: number
}

interface DragState {
  slotId: string
  originX: number
  originY: number
  pointerStartX: number
  pointerStartY: number
  moved: boolean
}

type ResizeHandle = 'nw' | 'ne' | 'sw' | 'se' | 'n' | 's' | 'e' | 'w'

interface ResizeState {
  slotId: string
  handle: ResizeHandle
  origin: { x: number; y: number; width: number; height: number }
  pointerStartX: number
  pointerStartY: number
  moved: boolean
}

/** Slot payload kept in the in-editor clipboard (no id). */
type ClipboardSlot = Omit<PlanogramSlot, 'id'>

function emptyDraft(): DraftState {
  return {
    id: null,
    name: '',
    description: '',
    imageBase64: '',
    imageWidth: 0,
    imageHeight: 0,
    slots: [],
  }
}

function planogramToDraft(planogram: Planogram): DraftState {
  return {
    id: planogram.id,
    name: planogram.name,
    description: planogram.description,
    imageBase64: planogram.imageBase64,
    imageWidth: planogram.imageWidth,
    imageHeight: planogram.imageHeight,
    slots: planogram.slots,
  }
}

function createSlotId(existing: PlanogramSlot[]): string {
  let index = existing.length + 1
  const used = new Set(existing.map((slot) => slot.id))
  while (used.has(`slot-${index}`)) {
    index += 1
  }
  return `slot-${index}`
}

function rectFromPoints(x1: number, y1: number, x2: number, y2: number): {
  x: number
  y: number
  width: number
  height: number
} {
  const left = Math.max(0, Math.min(x1, x2))
  const top = Math.max(0, Math.min(y1, y2))
  const right = Math.min(1, Math.max(x1, x2))
  const bottom = Math.min(1, Math.max(y1, y2))
  return {
    x: left,
    y: top,
    width: Math.max(0, right - left),
    height: Math.max(0, bottom - top),
  }
}

function toClipboardSlot(slot: PlanogramSlot): ClipboardSlot {
  return {
    x: slot.x,
    y: slot.y,
    width: slot.width,
    height: slot.height,
    itemName: slot.itemName,
    itemPrice: slot.itemPrice,
    itemStock: slot.itemStock,
    sku: slot.sku,
    notes: slot.notes,
  }
}

function clampSlotPosition(slot: ClipboardSlot, x: number, y: number): { x: number; y: number } {
  const maxX = Math.max(0, 1 - slot.width)
  const maxY = Math.max(0, 1 - slot.height)
  return {
    x: Math.max(0, Math.min(maxX, x)),
    y: Math.max(0, Math.min(maxY, y)),
  }
}

function applyResize(
  origin: { x: number; y: number; width: number; height: number },
  handle: ResizeHandle,
  dx: number,
  dy: number,
): { x: number; y: number; width: number; height: number } {
  let left = origin.x
  let top = origin.y
  let right = origin.x + origin.width
  let bottom = origin.y + origin.height

  if (handle.includes('w')) {
    left = Math.max(0, Math.min(right - MIN_SLOT_SIZE, origin.x + dx))
  }
  if (handle.includes('e')) {
    right = Math.min(1, Math.max(left + MIN_SLOT_SIZE, origin.x + origin.width + dx))
  }
  if (handle.includes('n')) {
    top = Math.max(0, Math.min(bottom - MIN_SLOT_SIZE, origin.y + dy))
  }
  if (handle.includes('s')) {
    bottom = Math.min(1, Math.max(top + MIN_SLOT_SIZE, origin.y + origin.height + dy))
  }

  return {
    x: left,
    y: top,
    width: Math.max(MIN_SLOT_SIZE, right - left),
    height: Math.max(MIN_SLOT_SIZE, bottom - top),
  }
}

/**
 * Prefer placing a pasted facing immediately to the right (same shelf row).
 * Fall back below, then a small diagonal nudge if the shelf edge is tight.
 */
function nextPastePosition(
  source: ClipboardSlot,
  existing: PlanogramSlot[],
  prefer: 'right' | 'below' | 'nudge' = 'right',
): { x: number; y: number } {
  const candidates: Array<{ x: number; y: number }> = []
  if (prefer === 'right' || prefer === 'nudge') {
    candidates.push({ x: source.x + source.width + PASTE_GAP, y: source.y })
  }
  if (prefer === 'below' || prefer === 'nudge' || prefer === 'right') {
    candidates.push({ x: source.x, y: source.y + source.height + PASTE_GAP })
  }
  candidates.push({
    x: source.x + PASTE_FALLBACK_NUDGE,
    y: source.y + PASTE_FALLBACK_NUDGE,
  })

  for (const candidate of candidates) {
    const clamped = clampSlotPosition(source, candidate.x, candidate.y)
    const overlapsSelfish =
      Math.abs(clamped.x - source.x) < 0.001 && Math.abs(clamped.y - source.y) < 0.001
    if (overlapsSelfish) {
      continue
    }
    const heavilyOverlaps = existing.some((slot) => {
      const overlapX = Math.min(slot.x + slot.width, clamped.x + source.width) - Math.max(slot.x, clamped.x)
      const overlapY = Math.min(slot.y + slot.height, clamped.y + source.height) - Math.max(slot.y, clamped.y)
      if (overlapX <= 0 || overlapY <= 0) {
        return false
      }
      const area = overlapX * overlapY
      return area > source.width * source.height * 0.55
    })
    if (!heavilyOverlaps) {
      return clamped
    }
  }

  return clampSlotPosition(source, source.x + PASTE_FALLBACK_NUDGE, source.y + PASTE_FALLBACK_NUDGE)
}

async function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(new Error('Could not read image.'))
    reader.readAsDataURL(file)
  })
}

function loadImageSize(dataUrl: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight })
    image.onerror = () => reject(new Error('Could not load image dimensions.'))
    image.src = dataUrl
  })
}

export function PlanogramPanel({ text, canWrite = true, readOnlyNotice }: PlanogramPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const [planograms, setPlanograms] = useState<Planogram[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [mode, setMode] = useState<'list' | 'editor'>('list')
  const [draft, setDraft] = useState<DraftState>(emptyDraft)
  const [selectedSlotId, setSelectedSlotId] = useState<string | null>(null)
  const [clipboardSlot, setClipboardSlot] = useState<ClipboardSlot | null>(null)
  const [drawState, setDrawState] = useState<DrawState | null>(null)
  const [dragState, setDragState] = useState<DragState | null>(null)
  const [resizeState, setResizeState] = useState<ResizeState | null>(null)
  const [busy, setBusy] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)

  const selectedSlot = useMemo(
    () => draft.slots.find((slot) => slot.id === selectedSlotId) ?? null,
    [draft.slots, selectedSlotId],
  )
  const selectedSlotRef = useRef<PlanogramSlot | null>(null)
  const clipboardRef = useRef<ClipboardSlot | null>(null)
  const draftSlotsRef = useRef<PlanogramSlot[]>([])
  const dragStateRef = useRef<DragState | null>(null)
  const resizeStateRef = useRef<ResizeState | null>(null)
  selectedSlotRef.current = selectedSlot
  clipboardRef.current = clipboardSlot
  draftSlotsRef.current = draft.slots
  dragStateRef.current = dragState
  resizeStateRef.current = resizeState

  const draftRect = useMemo(() => {
    if (!drawState) {
      return null
    }
    return rectFromPoints(drawState.startX, drawState.startY, drawState.currentX, drawState.currentY)
  }, [drawState])

  const refresh = useCallback(async (): Promise<void> => {
    setBusy(true)
    setErrorMessage(null)
    try {
      const result = await listPlanograms()
      setPlanograms(result.planograms)
      setActiveId(result.activePlanogramId)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : text.errors.loadFailed)
    } finally {
      setBusy(false)
    }
  }, [text])

  useEffect(() => {
    void refresh()
  }, [refresh])

  function startCreate(): void {
    setDraft(emptyDraft())
    setSelectedSlotId(null)
    setDrawState(null)
    setDragState(null)
    setMode('editor')
    setStatusMessage(null)
    setErrorMessage(null)
  }

  function startEdit(planogram: Planogram): void {
    setDraft(planogramToDraft(planogram))
    setSelectedSlotId(null)
    setDrawState(null)
    setDragState(null)
    setMode('editor')
    setStatusMessage(null)
    setErrorMessage(null)
  }

  async function handleImage(file: File | undefined): Promise<void> {
    if (!file) {
      return
    }
    if (!ACCEPTED_TYPES.includes(file.type) && !/\.(jpe?g|png|webp|gif)$/i.test(file.name)) {
      setErrorMessage(text.errors.invalidImage)
      return
    }
    try {
      const imageBase64 = await fileToDataUrl(file)
      const size = await loadImageSize(imageBase64)
      setDraft((previous) => ({
        ...previous,
        imageBase64,
        imageWidth: size.width,
        imageHeight: size.height,
      }))
      setErrorMessage(null)
    } catch {
      setErrorMessage(text.errors.invalidImage)
    }
  }

  function onImageInput(event: ChangeEvent<HTMLInputElement>): void {
    const file = event.target.files?.[0]
    void handleImage(file)
    event.target.value = ''
  }

  function pointerToNormalized(event: ReactPointerEvent<Element>): { x: number; y: number } | null {
    const element = canvasRef.current
    if (!element) {
      return null
    }
    const rect = element.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) {
      return null
    }
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    }
  }

  function onCanvasPointerDown(event: ReactPointerEvent<HTMLDivElement>): void {
    if (!draft.imageBase64 || busy || dragStateRef.current || resizeStateRef.current) {
      return
    }
    // Allow selecting/dragging existing slots via their buttons; only draw on empty canvas.
    const target = event.target as HTMLElement
    if (target.closest(`.${styles.slotRect}`) || target.closest(`.${styles.resizeHandle}`)) {
      return
    }
    const point = pointerToNormalized(event)
    if (!point) {
      return
    }
    event.currentTarget.setPointerCapture(event.pointerId)
    setSelectedSlotId(null)
    setDrawState({
      startX: point.x,
      startY: point.y,
      currentX: point.x,
      currentY: point.y,
    })
  }

  function onCanvasPointerMove(event: ReactPointerEvent<HTMLDivElement>): void {
    const point = pointerToNormalized(event)
    if (!point) {
      return
    }

    const activeResize = resizeStateRef.current
    if (activeResize) {
      const dx = point.x - activeResize.pointerStartX
      const dy = point.y - activeResize.pointerStartY
      if (!activeResize.moved && Math.hypot(dx, dy) >= 0.003) {
        const nextResize = { ...activeResize, moved: true }
        resizeStateRef.current = nextResize
        setResizeState(nextResize)
      }
      const nextRect = applyResize(activeResize.origin, activeResize.handle, dx, dy)
      setDraft((previous) => ({
        ...previous,
        slots: previous.slots.map((item) =>
          item.id === activeResize.slotId
            ? {
                ...item,
                x: nextRect.x,
                y: nextRect.y,
                width: nextRect.width,
                height: nextRect.height,
              }
            : item,
        ),
      }))
      return
    }

    const activeDrag = dragStateRef.current
    if (activeDrag) {
      const slot = draftSlotsRef.current.find((item) => item.id === activeDrag.slotId)
      if (!slot) {
        return
      }
      const dx = point.x - activeDrag.pointerStartX
      const dy = point.y - activeDrag.pointerStartY
      if (!activeDrag.moved && Math.hypot(dx, dy) >= 0.004) {
        const nextDrag = { ...activeDrag, moved: true }
        dragStateRef.current = nextDrag
        setDragState(nextDrag)
      }
      const position = clampSlotPosition(slot, activeDrag.originX + dx, activeDrag.originY + dy)
      setDraft((previous) => ({
        ...previous,
        slots: previous.slots.map((item) =>
          item.id === activeDrag.slotId ? { ...item, x: position.x, y: position.y } : item,
        ),
      }))
      return
    }

    if (!drawState) {
      return
    }
    setDrawState((previous) =>
      previous
        ? {
            ...previous,
            currentX: point.x,
            currentY: point.y,
          }
        : previous,
    )
  }

  function onCanvasPointerUp(event: ReactPointerEvent<HTMLDivElement>): void {
    const activeResize = resizeStateRef.current
    if (activeResize) {
      try {
        event.currentTarget.releasePointerCapture(event.pointerId)
      } catch {
        // ignore if capture already released
      }
      resizeStateRef.current = null
      setResizeState(null)
      if (activeResize.moved) {
        setStatusMessage(text.resized)
      }
      return
    }

    const activeDrag = dragStateRef.current
    if (activeDrag) {
      try {
        event.currentTarget.releasePointerCapture(event.pointerId)
      } catch {
        // ignore if capture already released
      }
      dragStateRef.current = null
      setDragState(null)
      if (activeDrag.moved) {
        setStatusMessage(text.moved)
      }
      return
    }

    if (!drawState) {
      return
    }
    try {
      event.currentTarget.releasePointerCapture(event.pointerId)
    } catch {
      // ignore if capture already released
    }
    const rect = rectFromPoints(drawState.startX, drawState.startY, drawState.currentX, drawState.currentY)
    setDrawState(null)
    if (rect.width < MIN_SLOT_SIZE || rect.height < MIN_SLOT_SIZE) {
      return
    }
    const id = createSlotId(draft.slots)
    const next: PlanogramSlot = {
      id,
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
      itemName: '',
      itemPrice: null,
      itemStock: 0,
      sku: '',
      notes: '',
    }
    setDraft((previous) => ({
      ...previous,
      slots: [...previous.slots, next].sort((a, b) => a.y - b.y || a.x - b.x || a.id.localeCompare(b.id)),
    }))
    setSelectedSlotId(id)
  }

  function onSlotPointerDown(event: ReactPointerEvent<HTMLButtonElement>, slot: PlanogramSlot): void {
    if (busy || !draft.imageBase64 || resizeStateRef.current) {
      return
    }
    event.stopPropagation()
    const point = pointerToNormalized(event)
    if (!point) {
      return
    }
    const nextDrag: DragState = {
      slotId: slot.id,
      originX: slot.x,
      originY: slot.y,
      pointerStartX: point.x,
      pointerStartY: point.y,
      moved: false,
    }
    dragStateRef.current = nextDrag
    setDragState(nextDrag)
    setSelectedSlotId(slot.id)
    setDrawState(null)
    // Capture on the canvas so move/up continue even if the pointer leaves the slot.
    canvasRef.current?.setPointerCapture(event.pointerId)
  }

  function onResizeHandlePointerDown(
    event: ReactPointerEvent<HTMLSpanElement>,
    slot: PlanogramSlot,
    handle: ResizeHandle,
  ): void {
    if (busy || !draft.imageBase64) {
      return
    }
    event.preventDefault()
    event.stopPropagation()
    const point = pointerToNormalized(event)
    if (!point) {
      return
    }
    const nextResize: ResizeState = {
      slotId: slot.id,
      handle,
      origin: { x: slot.x, y: slot.y, width: slot.width, height: slot.height },
      pointerStartX: point.x,
      pointerStartY: point.y,
      moved: false,
    }
    resizeStateRef.current = nextResize
    setResizeState(nextResize)
    dragStateRef.current = null
    setDragState(null)
    setSelectedSlotId(slot.id)
    setDrawState(null)
    canvasRef.current?.setPointerCapture(event.pointerId)
  }

  function updateSelectedSlot(patch: Partial<PlanogramSlot>): void {
    if (!selectedSlotId) {
      return
    }
    // Geometry is always per-slot. Item metadata (name/price/stock/sku/notes)
    // is shared across every region that currently has the same non-empty SKU.
    const geometryKeys = new Set(['x', 'y', 'width', 'height', 'id'])
    const metaPatch: Partial<PlanogramSlot> = {}
    const geometryPatch: Partial<PlanogramSlot> = {}
    for (const [key, value] of Object.entries(patch) as Array<
      [keyof PlanogramSlot, PlanogramSlot[keyof PlanogramSlot]]
    >) {
      if (geometryKeys.has(key)) {
        ;(geometryPatch as Record<string, unknown>)[key] = value
      } else {
        ;(metaPatch as Record<string, unknown>)[key] = value
      }
    }

    setDraft((previous) => {
      const selected = previous.slots.find((slot) => slot.id === selectedSlotId)
      if (!selected) {
        return previous
      }

      // Group by the SKU *before* this edit so changing SKU / name / stock / notes
      // on one facing updates every facing that currently shares that SKU.
      const groupSku = String(selected.sku || '').trim().toLowerCase()
      const hasMetaPatch = Object.keys(metaPatch).length > 0

      return {
        ...previous,
        slots: previous.slots.map((slot) => {
          if (slot.id === selectedSlotId) {
            return { ...slot, ...geometryPatch, ...metaPatch, id: slot.id }
          }
          if (!hasMetaPatch || !groupSku) {
            return slot
          }
          const slotSku = String(slot.sku || '').trim().toLowerCase()
          if (!slotSku || slotSku !== groupSku) {
            return slot
          }
          // Shared item fields only — keep each region's own rectangle.
          return { ...slot, ...metaPatch, id: slot.id }
        }),
      }
    })
  }

  // These four are memoized (and read the selected slot / clipboard / draft
  // through refs, never captured state) so the global keydown handler below can
  // list them as effect dependencies without re-subscribing on every keystroke
  // or capturing a stale closure.
  const deleteSelectedSlot = useCallback((): void => {
    const slot = selectedSlotRef.current
    if (!slot) {
      return
    }
    setDraft((previous) => ({
      ...previous,
      slots: previous.slots.filter((item) => item.id !== slot.id),
    }))
    setSelectedSlotId(null)
  }, [])

  const copySelectedSlot = useCallback((): boolean => {
    const slot = selectedSlotRef.current
    if (!slot) {
      setErrorMessage(text.errors.copyRequiresSelection)
      return false
    }
    const payload = toClipboardSlot(slot)
    setClipboardSlot(payload)
    clipboardRef.current = payload
    setErrorMessage(null)
    setStatusMessage(text.copied)
    return true
  }, [text])

  const pasteClipboardSlot = useCallback(
    (prefer: 'right' | 'below' | 'nudge' = 'right'): boolean => {
      const source = clipboardRef.current
      if (!source) {
        setErrorMessage(text.errors.pasteEmpty)
        return false
      }
      const existing = draftSlotsRef.current
      const position = nextPastePosition(source, existing, prefer)
      const id = createSlotId(existing)
      const next: PlanogramSlot = {
        id,
        ...source,
        x: position.x,
        y: position.y,
      }
      setDraft((previous) => ({
        ...previous,
        slots: [...previous.slots, next].sort((a, b) => a.y - b.y || a.x - b.x || a.id.localeCompare(b.id)),
      }))
      setSelectedSlotId(id)
      setErrorMessage(null)
      setStatusMessage(text.pasted)
      return true
    },
    [text],
  )

  const duplicateSelectedSlot = useCallback(
    (prefer: 'right' | 'below' = 'right'): boolean => {
      const slot = selectedSlotRef.current
      if (!slot) {
        setErrorMessage(text.errors.copyRequiresSelection)
        return false
      }
      const payload = toClipboardSlot(slot)
      setClipboardSlot(payload)
      clipboardRef.current = payload
      return pasteClipboardSlot(prefer)
    },
    [text, pasteClipboardSlot],
  )

  useEffect(() => {
    if (mode !== 'editor') {
      return
    }

    function isEditableTarget(target: EventTarget | null): boolean {
      if (!(target instanceof HTMLElement)) {
        return false
      }
      const tag = target.tagName
      return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable
    }

    function onKeyDown(event: KeyboardEvent): void {
      if (busy) {
        return
      }
      const key = event.key.toLowerCase()
      const hasModifier = event.metaKey || event.ctrlKey

      // Delete/Backspace removes the selected region when focus is not in a text field.
      if ((event.key === 'Delete' || event.key === 'Backspace') && !hasModifier) {
        if (isEditableTarget(event.target)) {
          return
        }
        if (selectedSlotRef.current) {
          event.preventDefault()
          deleteSelectedSlot()
          setStatusMessage(text.regionDeleted)
        }
        return
      }

      if (!hasModifier) {
        return
      }
      // Allow normal cut/copy/paste inside form fields.
      if (isEditableTarget(event.target) && (key === 'c' || key === 'v' || key === 'x' || key === 'a')) {
        return
      }

      if (key === 'c') {
        event.preventDefault()
        copySelectedSlot()
        return
      }
      if (key === 'v') {
        event.preventDefault()
        pasteClipboardSlot(event.shiftKey ? 'below' : 'right')
        return
      }
      if (key === 'd') {
        event.preventDefault()
        duplicateSelectedSlot(event.shiftKey ? 'below' : 'right')
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [mode, busy, text, copySelectedSlot, pasteClipboardSlot, duplicateSelectedSlot, deleteSelectedSlot])

  async function saveDraft(event: FormEvent): Promise<void> {
    event.preventDefault()
    if (!draft.name.trim()) {
      setErrorMessage(text.errors.nameRequired)
      return
    }
    if (!draft.imageBase64) {
      setErrorMessage(text.errors.imageRequired)
      return
    }
    if (draft.slots.length === 0) {
      setErrorMessage(text.errors.slotsRequired)
      return
    }

    setBusy(true)
    setErrorMessage(null)
    try {
      const payload = {
        name: draft.name.trim(),
        description: draft.description.trim(),
        imageBase64: draft.imageBase64,
        imageWidth: draft.imageWidth,
        imageHeight: draft.imageHeight,
        slots: draft.slots,
      }
      if (draft.id) {
        await updatePlanogram(draft.id, payload)
      } else {
        await createPlanogram(payload)
      }
      setStatusMessage(text.saved)
      setMode('list')
      setDraft(emptyDraft())
      setSelectedSlotId(null)
      await refresh()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : text.errors.saveFailed)
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(id: string): Promise<void> {
    if (!window.confirm(text.confirmDelete)) {
      return
    }
    setBusy(true)
    setErrorMessage(null)
    try {
      await deletePlanogram(id)
      await refresh()
      setStatusMessage(text.deleted)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : text.errors.deleteFailed)
    } finally {
      setBusy(false)
    }
  }

  async function handleActivate(id: string): Promise<void> {
    setBusy(true)
    setErrorMessage(null)
    try {
      const active = await setActivePlanogram(id)
      setActiveId(active)
      setStatusMessage(text.activated)
      await refresh()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : text.errors.activateFailed)
    } finally {
      setBusy(false)
    }
  }

  if (mode === 'editor') {
    return (
      <section className={styles.panel} aria-labelledby="planogram-editor-title">
        <header className={styles.header}>
          <div>
            <h2 id="planogram-editor-title" className={styles.title}>
              {draft.id ? text.editTitle : text.createTitle}
            </h2>
            <p className={styles.subtitle}>{text.editorSubtitle}</p>
          </div>
          <button type="button" className={`${styles.ghostButton} glass-lens`} disabled={busy} onClick={() => setMode('list')}>
            {text.backToList}
          </button>
        </header>

        <form className={styles.editor} onSubmit={(event) => void saveDraft(event)}>
          <div className={styles.metaGrid}>
            <label className={styles.field}>
              <span>{text.name}</span>
              <input
                className={styles.input}
                value={draft.name}
                disabled={busy}
                onChange={(event) => setDraft((previous) => ({ ...previous, name: event.target.value }))}
                placeholder={text.namePlaceholder}
              />
            </label>
            <label className={`${styles.field} ${styles.fullWidth}`}>
              <span>{text.description}</span>
              <input
                className={styles.input}
                value={draft.description}
                disabled={busy}
                onChange={(event) => setDraft((previous) => ({ ...previous, description: event.target.value }))}
                placeholder={text.descriptionPlaceholder}
              />
            </label>
          </div>

          <div className={styles.workspace}>
            <div className={styles.canvasCard}>
              <div className={styles.canvasToolbar}>
                <div>
                  <p className={styles.canvasHint}>{text.drawHint}</p>
                  <p className={styles.shortcutHint}>{text.shortcutsHint}</p>
                </div>
                <div className={styles.actions}>
                  <button
                    type="button"
                    className={`${styles.ghostButton} glass-lens`}
                    disabled={busy || !selectedSlot}
                    onClick={() => copySelectedSlot()}
                    title={text.copyShortcut}
                  >
                    {text.copyRegion}
                  </button>
                  <button
                    type="button"
                    className={`${styles.ghostButton} glass-lens`}
                    disabled={busy || !clipboardSlot}
                    onClick={() => pasteClipboardSlot('right')}
                    title={text.pasteShortcut}
                  >
                    {text.pasteRegion}
                  </button>
                  <button
                    type="button"
                    className={`${styles.ghostButton} glass-lens`}
                    disabled={busy || !selectedSlot}
                    onClick={() => duplicateSelectedSlot('right')}
                    title={text.duplicateShortcut}
                  >
                    {text.duplicateRight}
                  </button>
                  <button
                    type="button"
                    className={`${styles.ghostButton} glass-lens`}
                    disabled={busy || !selectedSlot}
                    onClick={() => {
                      deleteSelectedSlot()
                      setStatusMessage(text.regionDeleted)
                    }}
                    title={text.deleteShortcut}
                  >
                    {text.deleteRegion}
                  </button>
                  <button
                    type="button"
                    className={`${styles.ghostButton} glass-lens`}
                    disabled={busy}
                    onClick={() => inputRef.current?.click()}
                  >
                    {draft.imageBase64 ? text.replaceImage : text.uploadImage}
                  </button>
                  <input
                    ref={inputRef}
                    className={styles.fileInput}
                    type="file"
                    accept="image/jpeg,image/png,image/webp,image/gif"
                    onChange={onImageInput}
                  />
                </div>
              </div>
              <p className={styles.clipboardHint}>
                {clipboardSlot
                  ? text.clipboardReady.replace('{name}', clipboardSlot.itemName || clipboardSlot.sku || text.emptyRegion)
                  : text.clipboardEmpty}
              </p>

              <div
                ref={canvasRef}
                className={`${styles.canvas} ${draft.imageBase64 ? styles.canvasDrawable : ''} ${dragState || resizeState ? styles.canvasDragging : ''}`}
                onPointerDown={onCanvasPointerDown}
                onPointerMove={onCanvasPointerMove}
                onPointerUp={onCanvasPointerUp}
                onPointerCancel={() => {
                  setDrawState(null)
                  dragStateRef.current = null
                  setDragState(null)
                  resizeStateRef.current = null
                  setResizeState(null)
                }}
              >
                {draft.imageBase64 ? (
                  <img className={styles.shelfImage} src={draft.imageBase64} alt={text.imageAlt} draggable={false} />
                ) : (
                  <div className={styles.canvasEmpty}>{text.imageEmpty}</div>
                )}

                {draft.slots.map((slot) => {
                  const filled = Boolean(slot.itemName || slot.sku)
                  const isSelected = selectedSlotId === slot.id
                  const isDragging = dragState?.slotId === slot.id
                  const isResizing = resizeState?.slotId === slot.id
                  const handles: ResizeHandle[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']
                  return (
                    <button
                      key={slot.id}
                      type="button"
                      className={`${styles.slotRect} ${filled ? styles.slotFilled : ''} ${isSelected ? styles.slotSelected : ''} ${isDragging || isResizing ? styles.slotDragging : ''}`}
                      style={{
                        left: `${slot.x * 100}%`,
                        top: `${slot.y * 100}%`,
                        width: `${slot.width * 100}%`,
                        height: `${slot.height * 100}%`,
                      }}
                      onClick={(event) => {
                        event.stopPropagation()
                        // Keep selection after a pure click (no drag/resize).
                        if (!dragStateRef.current?.moved && !resizeStateRef.current?.moved) {
                          setSelectedSlotId(slot.id)
                        }
                      }}
                      onPointerDown={(event) => onSlotPointerDown(event, slot)}
                    >
                      <span className={styles.slotLabel}>{slot.itemName || slot.sku || text.emptyRegion}</span>
                      {isSelected
                        ? handles.map((handle) => (
                            <span
                              key={handle}
                              className={`${styles.resizeHandle} ${styles[`handle_${handle}`]}`}
                              onPointerDown={(event) => onResizeHandlePointerDown(event, slot, handle)}
                              aria-label={`${text.resizeHandle} ${handle}`}
                            />
                          ))
                        : null}
                    </button>
                  )
                })}

                {draftRect ? (
                  <div
                    className={styles.draftRect}
                    style={{
                      left: `${draftRect.x * 100}%`,
                      top: `${draftRect.y * 100}%`,
                      width: `${draftRect.width * 100}%`,
                      height: `${draftRect.height * 100}%`,
                    }}
                  />
                ) : null}
              </div>
              <p className={styles.regionCount}>
                {text.regionCount.replace('{count}', String(draft.slots.length))}
              </p>
            </div>

            <aside className={styles.slotEditor}>
              <h3 className={styles.boxLabel}>{text.slotEditor}</h3>
              {selectedSlot ? (
                <div className={styles.slotFields}>
                  <p className={styles.selectedCoord}>
                    {text.selectedRegion
                      .replace('{id}', selectedSlot.id)
                      .replace('{x}', (selectedSlot.x * 100).toFixed(0))
                      .replace('{y}', (selectedSlot.y * 100).toFixed(0))}
                  </p>
                  <label className={styles.field}>
                    <span>{text.itemName}</span>
                    <input
                      className={styles.input}
                      value={selectedSlot.itemName}
                      disabled={busy}
                      onChange={(event) => updateSelectedSlot({ itemName: event.target.value })}
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{text.sku}</span>
                    <input
                      className={styles.input}
                      value={selectedSlot.sku}
                      disabled={busy}
                      onChange={(event) => updateSelectedSlot({ sku: event.target.value })}
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{text.itemPrice}</span>
                    <input
                      className={styles.input}
                      type="number"
                      min={0}
                      step="0.01"
                      value={selectedSlot.itemPrice ?? ''}
                      disabled={busy}
                      onChange={(event) =>
                        updateSelectedSlot({
                          itemPrice: event.target.value === '' ? null : Number(event.target.value),
                        })
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{text.itemStock}</span>
                    <input
                      className={styles.input}
                      type="number"
                      min={0}
                      step={1}
                      value={selectedSlot.itemStock}
                      disabled={busy}
                      onChange={(event) =>
                        updateSelectedSlot({ itemStock: Math.max(0, Number(event.target.value) || 0) })
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{text.notes}</span>
                    <textarea
                      className={styles.textarea}
                      value={selectedSlot.notes}
                      disabled={busy}
                      rows={3}
                      onChange={(event) => updateSelectedSlot({ notes: event.target.value })}
                    />
                  </label>
                  <div className={styles.slotActions}>
                    <button
                      type="button"
                      className={`${styles.ghostButton} glass-lens`}
                      disabled={busy}
                      onClick={() => copySelectedSlot()}
                      title={text.copyShortcut}
                    >
                      {text.copyRegion}
                    </button>
                    <button
                      type="button"
                      className={`${styles.ghostButton} glass-lens`}
                      disabled={busy || !clipboardSlot}
                      onClick={() => pasteClipboardSlot('right')}
                      title={text.pasteShortcut}
                    >
                      {text.pasteRegion}
                    </button>
                    <button
                      type="button"
                      className={`${styles.ghostButton} glass-lens`}
                      disabled={busy}
                      onClick={() => duplicateSelectedSlot('right')}
                      title={text.duplicateShortcut}
                    >
                      {text.duplicateRight}
                    </button>
                    <button
                      type="button"
                      className={`${styles.ghostButton} glass-lens`}
                      disabled={busy}
                      onClick={() => duplicateSelectedSlot('below')}
                    >
                      {text.duplicateBelow}
                    </button>
                    <button type="button" className={`${styles.ghostButton} glass-lens`} disabled={busy} onClick={deleteSelectedSlot}>
                      {text.deleteRegion}
                    </button>
                  </div>
                </div>
              ) : (
                <div className={styles.slotFields}>
                  <p className={styles.emptyCopy}>{text.selectRegionHint}</p>
                  <button
                    type="button"
                    className={`${styles.ghostButton} glass-lens`}
                    disabled={busy || !clipboardSlot}
                    onClick={() => pasteClipboardSlot('right')}
                    title={text.pasteShortcut}
                  >
                    {text.pasteRegion}
                  </button>
                </div>
              )}
            </aside>
          </div>

          {errorMessage ? <p className={styles.errorLine}>{errorMessage}</p> : null}
          {statusMessage ? <p className={styles.statusLine}>{statusMessage}</p> : null}

          <div className={styles.footerActions}>
            <button type="submit" className={`${styles.primaryButton} glass-lens`} disabled={busy}>
              {busy ? text.saving : text.save}
            </button>
            <button type="button" className={`${styles.ghostButton} glass-lens`} disabled={busy} onClick={() => setMode('list')}>
              {text.cancel}
            </button>
          </div>
        </form>
      </section>
    )
  }

  return (
    <section className={styles.panel} aria-labelledby="planogram-panel-title">
      <header className={styles.header}>
        <div>
          <h2 id="planogram-panel-title" className={styles.title}>
            {text.title}
          </h2>
          <p className={styles.subtitle}>{text.subtitle}</p>
        </div>
        <div className={styles.actions}>
          <button type="button" className={`${styles.ghostButton} glass-lens`} disabled={busy} onClick={() => void refresh()}>
            {busy ? text.loading : text.refresh}
          </button>
          {canWrite ? (
            <button type="button" className={`${styles.primaryButton} glass-lens`} disabled={busy} onClick={startCreate}>
              {text.addNew}
            </button>
          ) : null}
        </div>
      </header>

      {!canWrite && readOnlyNotice ? <p className={styles.statusLine}>{readOnlyNotice}</p> : null}
      {errorMessage ? <p className={styles.errorLine}>{errorMessage}</p> : null}
      {statusMessage ? <p className={styles.statusLine}>{statusMessage}</p> : null}

      {planograms.length === 0 ? (
        <div className={styles.emptyState}>
          <h3 className={styles.emptyTitle}>{text.emptyTitle}</h3>
          <p className={styles.emptyCopy}>{text.emptyCopy}</p>
          {canWrite ? (
            <button type="button" className={`${styles.primaryButton} glass-lens`} onClick={startCreate}>
              {text.addNew}
            </button>
          ) : null}
        </div>
      ) : (
        <div className={styles.list}>
          {planograms.map((planogram) => {
            const isActive = planogram.id === activeId
            const filled = planogram.slots.filter((slot) => slot.itemName || slot.sku).length
            return (
              <article key={planogram.id} className={`${styles.card} ${isActive ? styles.cardActive : ''}`}>
                <div className={styles.cardMedia}>
                  {planogram.imageBase64 ? (
                    <img className={styles.cardImage} src={planogram.imageBase64} alt={planogram.name} />
                  ) : (
                    <div className={styles.cardImagePlaceholder}>{text.noImage}</div>
                  )}
                  <div className={styles.cardOverlay}>
                    {planogram.slots.map((slot) => (
                      <span
                        key={slot.id}
                        className={styles.cardSlot}
                        style={{
                          left: `${slot.x * 100}%`,
                          top: `${slot.y * 100}%`,
                          width: `${slot.width * 100}%`,
                          height: `${slot.height * 100}%`,
                        }}
                      />
                    ))}
                  </div>
                </div>
                <div className={styles.cardBody}>
                  <div className={styles.cardTitleRow}>
                    <h3 className={styles.cardTitle}>{planogram.name}</h3>
                    {isActive ? <span className={styles.badge}>{text.activeBadge}</span> : null}
                  </div>
                  <p className={styles.cardMeta}>
                    {text.regionSummary
                      .replace('{count}', String(planogram.slots.length))
                      .replace('{filled}', String(filled))}
                  </p>
                  <p className={styles.cardDescription}>{planogram.description || text.noDescription}</p>
                  {canWrite ? (
                    <div className={styles.cardActions}>
                      {!isActive ? (
                        <button
                          type="button"
                          className={`${styles.primaryButton} glass-lens`}
                          disabled={busy}
                          onClick={() => void handleActivate(planogram.id)}
                        >
                          {text.useThis}
                        </button>
                      ) : (
                        <button type="button" className={`${styles.primaryButton} glass-lens`} disabled>
                          {text.inUse}
                        </button>
                      )}
                      <button type="button" className={`${styles.ghostButton} glass-lens`} disabled={busy} onClick={() => startEdit(planogram)}>
                        {text.edit}
                      </button>
                      <button
                        type="button"
                        className={`${styles.ghostButton} glass-lens`}
                        disabled={busy}
                        onClick={() => void handleDelete(planogram.id)}
                      >
                        {text.delete}
                      </button>
                    </div>
                  ) : isActive ? (
                    <div className={styles.cardActions}>
                      <span className={styles.badge}>{text.inUse}</span>
                    </div>
                  ) : null}
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
