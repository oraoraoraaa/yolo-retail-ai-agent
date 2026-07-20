import type {
  Planogram,
  PlanogramCreatePayload,
  PlanogramListResult,
  PlanogramMatchResult,
  PlanogramSlot,
  PlanogramUpdatePayload,
} from '@/types/planogram'

import { apiFetch, getApiBaseUrl } from './client'

const PLANOGRAM_PATH = '/api/v1/planograms'

const LOCAL_STORAGE_KEY = 'yolo-retail-planograms-v2'
const LOCAL_ACTIVE_KEY = 'yolo-retail-active-planogram-v2'

interface LocalPlanogramState {
  planograms: Planogram[]
  activePlanogramId: string | null
  counter: number
}

function nowIso(): string {
  return new Date().toISOString()
}

function seedSlots(): PlanogramSlot[] {
  const labels: Array<[string, number, number, string]> = [
    ['Brand Y Soda 330ml', 1.29, 24, 'BY-SODA-330'],
    ['Sparkling Water 500ml', 0.99, 18, 'SW-500'],
    ['Cola Classic 330ml', 1.19, 30, 'CC-330'],
    ['Orange Juice 1L', 2.49, 12, 'OJ-1L'],
    ['Iced Tea Lemon 500ml', 1.49, 16, 'IT-LEM-500'],
    ['Energy Drink 250ml', 1.99, 20, 'ED-250'],
    ['Still Water 500ml', 0.79, 40, 'W-500'],
    ['Sports Drink 500ml', 1.59, 14, 'SD-500'],
    ['Coffee Can 240ml', 1.69, 10, 'CF-240'],
    ['Milk 1L', 1.89, 8, 'MK-1L'],
    ['Yogurt Drink 200ml', 1.09, 15, 'YD-200'],
    ['Vitamin Water 500ml', 1.79, 11, 'VW-500'],
  ]
  return labels.map(([itemName, itemPrice, itemStock, sku], index) => {
    const row = Math.floor(index / 4)
    const col = index % 4
    return {
      id: `slot-${String(index + 1).padStart(2, '0')}`,
      x: col * 0.25 + 0.01,
      y: row * (1 / 3) + 0.01,
      width: 0.23,
      height: 1 / 3 - 0.02,
      itemName,
      itemPrice,
      itemStock,
      sku,
      notes: '',
    }
  })
}

function emptyLocalState(): LocalPlanogramState {
  return {
    planograms: [
      {
        id: 'plan-local-0001',
        name: 'Aisle 3 · Beverages',
        description: 'Demo planogram with freehand facing rectangles (seed).',
        imageBase64: '',
        imageWidth: 0,
        imageHeight: 0,
        slots: seedSlots(),
        createdAt: nowIso(),
        updatedAt: nowIso(),
      },
    ],
    activePlanogramId: 'plan-local-0001',
    counter: 2,
  }
}

function readLocalState(): LocalPlanogramState {
  try {
    const raw = window.localStorage.getItem(LOCAL_STORAGE_KEY)
    if (!raw) {
      const seed = emptyLocalState()
      writeLocalState(seed)
      return seed
    }
    const parsed = JSON.parse(raw) as LocalPlanogramState
    if (!Array.isArray(parsed.planograms)) {
      return emptyLocalState()
    }
    // Drop legacy row/col-only planograms if any slipped into storage.
    const planograms = parsed.planograms
      .map((planogram) => ({
        ...planogram,
        slots: Array.isArray(planogram.slots)
          ? planogram.slots.filter(
              (slot) =>
                typeof slot === 'object' &&
                slot !== null &&
                typeof (slot as PlanogramSlot).id === 'string' &&
                typeof (slot as PlanogramSlot).x === 'number' &&
                typeof (slot as PlanogramSlot).width === 'number',
            )
          : [],
      }))
      .filter(Boolean)
    return { ...parsed, planograms }
  } catch {
    return emptyLocalState()
  }
}

function writeLocalState(state: LocalPlanogramState): void {
  window.localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(state))
  if (state.activePlanogramId) {
    window.localStorage.setItem(LOCAL_ACTIVE_KEY, state.activePlanogramId)
  } else {
    window.localStorage.removeItem(LOCAL_ACTIVE_KEY)
  }
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}

function normalizeSlots(slots: PlanogramCreatePayload['slots']): PlanogramSlot[] {
  const seen = new Set<string>()
  const normalized: PlanogramSlot[] = []
  slots.forEach((slot, index) => {
    let x = clamp01(Number(slot.x) || 0)
    let y = clamp01(Number(slot.y) || 0)
    let width = Math.max(0, Number(slot.width) || 0)
    let height = Math.max(0, Number(slot.height) || 0)
    if (x + width > 1) {
      width = 1 - x
    }
    if (y + height > 1) {
      height = 1 - y
    }
    if (width < 0.005 || height < 0.005) {
      return
    }
    let id = (slot.id || '').trim() || `slot-${index + 1}`
    const base = id
    let suffix = 2
    while (seen.has(id)) {
      id = `${base}-${suffix}`
      suffix += 1
    }
    seen.add(id)
    normalized.push({
      id,
      x,
      y,
      width,
      height,
      itemName: slot.itemName?.trim() ?? '',
      itemPrice: slot.itemPrice ?? null,
      itemStock: Math.max(0, Number(slot.itemStock) || 0),
      sku: slot.sku?.trim() ?? '',
      notes: slot.notes?.trim() ?? '',
    })
  })
  return normalized.sort((a, b) => a.y - b.y || a.x - b.x || a.id.localeCompare(b.id))
}

function localListPlanograms(): PlanogramListResult {
  const state = readLocalState()
  return {
    planograms: [...state.planograms].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
    activePlanogramId: state.activePlanogramId,
  }
}

function localCreatePlanogram(payload: PlanogramCreatePayload): Planogram {
  const state = readLocalState()
  const id = `plan-local-${String(state.counter).padStart(4, '0')}`
  const now = nowIso()
  const planogram: Planogram = {
    id,
    name: payload.name.trim() || `Planogram ${id}`,
    description: payload.description?.trim() ?? '',
    imageBase64: payload.imageBase64 ?? '',
    imageWidth: payload.imageWidth ?? 0,
    imageHeight: payload.imageHeight ?? 0,
    slots: normalizeSlots(payload.slots),
    createdAt: now,
    updatedAt: now,
  }
  state.counter += 1
  state.planograms = [planogram, ...state.planograms]
  if (!state.activePlanogramId) {
    state.activePlanogramId = planogram.id
  }
  writeLocalState(state)
  return planogram
}

function localUpdatePlanogram(id: string, payload: PlanogramUpdatePayload): Planogram {
  const state = readLocalState()
  const index = state.planograms.findIndex((item) => item.id === id)
  if (index < 0) {
    throw new Error('Planogram not found.')
  }
  const existing = state.planograms[index]
  const updated: Planogram = {
    ...existing,
    name: payload.name?.trim() || existing.name,
    description: payload.description !== undefined ? payload.description.trim() : existing.description,
    imageBase64: payload.imageBase64 ?? existing.imageBase64,
    imageWidth: payload.imageWidth ?? existing.imageWidth,
    imageHeight: payload.imageHeight ?? existing.imageHeight,
    slots: payload.slots ? normalizeSlots(payload.slots) : normalizeSlots(existing.slots),
    updatedAt: nowIso(),
  }
  state.planograms[index] = updated
  writeLocalState(state)
  return updated
}

function localDeletePlanogram(id: string): void {
  const state = readLocalState()
  state.planograms = state.planograms.filter((item) => item.id !== id)
  if (state.activePlanogramId === id) {
    state.activePlanogramId = state.planograms[0]?.id ?? null
  }
  writeLocalState(state)
}

function localSetActivePlanogram(id: string | null): string | null {
  const state = readLocalState()
  if (id && !state.planograms.some((item) => item.id === id)) {
    throw new Error('Planogram not found.')
  }
  state.activePlanogramId = id
  writeLocalState(state)
  return id
}

function isGapLabel(label: string): boolean {
  const lowered = label.trim().toLowerCase()
  return lowered.includes('gap') || lowered.includes('empty') || label.includes('缺') || label.includes('空')
}

function containsSlot(slot: PlanogramSlot, cx: number, cy: number): boolean {
  return cx >= slot.x && cx <= slot.x + slot.width && cy >= slot.y && cy <= slot.y + slot.height
}

function pointInRegion(
  region: { x1: number; y1: number; x2: number; y2: number },
  cx: number,
  cy: number,
): boolean {
  const loX = Math.min(region.x1, region.x2)
  const hiX = Math.max(region.x1, region.x2)
  const loY = Math.min(region.y1, region.y2)
  const hiY = Math.max(region.y1, region.y2)
  return cx >= loX && cx <= hiX && cy >= loY && cy <= hiY
}

function localMatchPlanogram(
  planogram: Planogram,
  visionModelResponse: {
    detections?: Array<{
      label: string
      confidence?: number
      obscured?: boolean
      normalizedBox?: { x1: number; y1: number; x2: number; y2: number }
    }>
    occlusion?: { regions?: Array<{ x1: number; y1: number; x2: number; y2: number }> }
  },
): PlanogramMatchResult {
  const matches: PlanogramMatchResult['matches'] = []
  const gapMatches: PlanogramMatchResult['gapMatches'] = []
  const obscuredMatches: PlanogramMatchResult['obscuredMatches'] = []
  const missingMap = new Map<string, PlanogramMatchResult['missingItems'][number]>()
  const obscuredSlotIds = new Set<string>()
  const occlusionRegions = visionModelResponse.occlusion?.regions ?? []

  for (const detection of visionModelResponse.detections ?? []) {
    const box = detection.normalizedBox
    if (!box) {
      continue
    }
    const cx = (box.x1 + box.x2) / 2
    const cy = (box.y1 + box.y2) / 2
    const candidates = planogram.slots.filter((slot) => containsSlot(slot, cx, cy))
    const slot =
      candidates.length === 0
        ? null
        : candidates.reduce((best, current) =>
            current.width * current.height < best.width * best.height ? current : best,
          )
    const isGap = isGapLabel(detection.label)
    const isObscured = Boolean(detection.obscured)
    const status = isGap && isObscured ? 'obscured' : isGap ? 'gap' : 'product'
    const entry = {
      detectionLabel: detection.label,
      confidence: detection.confidence,
      slotId: slot?.id ?? null,
      center: { x: cx, y: cy },
      slot,
      status,
      obscured: isObscured,
    }
    matches.push(entry)
    if (status === 'obscured') {
      obscuredMatches.push(entry)
      if (slot) {
        obscuredSlotIds.add(slot.id)
      }
      continue
    }
    if (status === 'gap') {
      gapMatches.push(entry)
      if (slot && (slot.itemName || slot.sku)) {
        missingMap.set(slot.id, {
          slotId: slot.id,
          x: slot.x,
          y: slot.y,
          width: slot.width,
          height: slot.height,
          itemName: slot.itemName,
          itemPrice: slot.itemPrice,
          itemStock: slot.itemStock,
          sku: slot.sku,
          notes: slot.notes,
          confidence: detection.confidence,
        })
      }
    }
  }

  // Slots whose center falls inside an occlusion region are obscured even with
  // no detection of their own (a fully covered facing).
  for (const slot of planogram.slots) {
    if (obscuredSlotIds.has(slot.id)) {
      continue
    }
    const cx = slot.x + slot.width / 2
    const cy = slot.y + slot.height / 2
    if (occlusionRegions.some((region) => pointInRegion(region, cx, cy))) {
      obscuredSlotIds.add(slot.id)
      obscuredMatches.push({
        detectionLabel: '',
        confidence: undefined,
        slotId: slot.id,
        center: { x: cx, y: cy },
        slot,
        status: 'obscured',
        obscured: true,
      })
    }
  }

  // Never report an obscured slot as missing.
  for (const slotId of obscuredSlotIds) {
    missingMap.delete(slotId)
  }

  const missingItems = Array.from(missingMap.values())

  // Out-of-stock is planogram ground truth (staff-entered stock): every slot
  // with stock <= 0 needs a backroom ticket even when no gap was detected.
  // Mirrors the backend planogram_match logic.
  const outOfStockSlots: PlanogramMatchResult['outOfStockSlots'] = []
  for (const slot of planogram.slots) {
    if (slot.itemStock > 0) {
      continue
    }
    if (!(slot.itemName || slot.sku)) {
      continue
    }
    outOfStockSlots.push({
      slotId: slot.id,
      x: slot.x,
      y: slot.y,
      width: slot.width,
      height: slot.height,
      itemName: slot.itemName,
      itemPrice: slot.itemPrice,
      itemStock: slot.itemStock,
      sku: slot.sku,
      notes: slot.notes,
    })
  }
  const obscuredSuffix =
    obscuredSlotIds.size > 0 ? ` ${obscuredSlotIds.size} facing(s) obscured (skipped).` : ''
  let summary = `No gaps matched against planogram '${planogram.name}'.`
  if (missingItems.length > 0) {
    const names = missingItems.map((item) => item.itemName || item.sku || item.slotId).join(', ')
    summary = `Matched ${gapMatches.length} gap(s) to planogram '${planogram.name}'. Likely missing: ${names}.${obscuredSuffix}`
  } else if (gapMatches.length > 0) {
    summary = `Matched ${gapMatches.length} gap(s) on planogram '${planogram.name}', but those regions have no assigned SKU metadata.${obscuredSuffix}`
  } else if (obscuredSlotIds.size > 0) {
    summary = `No confirmed gaps on planogram '${planogram.name}'.${obscuredSuffix}`
  }

  return {
    planogramId: planogram.id,
    planogramName: planogram.name,
    slotCount: planogram.slots.length,
    matches,
    gapMatches,
    obscuredMatches,
    missingItems,
    outOfStockSlots,
    summary,
  }
}

export async function listPlanograms(): Promise<PlanogramListResult> {
  if (!getApiBaseUrl()) {
    return localListPlanograms()
  }
  try {
    const response = await apiFetch(PLANOGRAM_PATH)
    return (await response.json()) as PlanogramListResult
  } catch {
    return localListPlanograms()
  }
}

export async function createPlanogram(payload: PlanogramCreatePayload): Promise<Planogram> {
  if (!getApiBaseUrl()) {
    return localCreatePlanogram(payload)
  }
  try {
    const response = await apiFetch(PLANOGRAM_PATH, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return (await response.json()) as Planogram
  } catch {
    return localCreatePlanogram(payload)
  }
}

export async function updatePlanogram(id: string, payload: PlanogramUpdatePayload): Promise<Planogram> {
  if (!getApiBaseUrl()) {
    return localUpdatePlanogram(id, payload)
  }
  try {
    const response = await apiFetch(`${PLANOGRAM_PATH}/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return (await response.json()) as Planogram
  } catch {
    return localUpdatePlanogram(id, payload)
  }
}

export async function deletePlanogram(id: string): Promise<void> {
  if (!getApiBaseUrl()) {
    localDeletePlanogram(id)
    return
  }
  try {
    await apiFetch(`${PLANOGRAM_PATH}/${id}`, { method: 'DELETE' })
  } catch {
    localDeletePlanogram(id)
  }
}

export async function setActivePlanogram(id: string | null): Promise<string | null> {
  if (!getApiBaseUrl()) {
    return localSetActivePlanogram(id)
  }
  try {
    const response = await apiFetch(`${PLANOGRAM_PATH}/active`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ planogramId: id }),
    })
    const body = (await response.json()) as { activePlanogramId: string | null }
    return body.activePlanogramId
  } catch {
    return localSetActivePlanogram(id)
  }
}

export async function matchPlanogramDetections(
  planogramId: string,
  visionModelResponse: unknown,
): Promise<PlanogramMatchResult | null> {
  if (!getApiBaseUrl()) {
    const list = localListPlanograms()
    const planogram = list.planograms.find((item) => item.id === planogramId)
    if (!planogram) {
      return null
    }
    return localMatchPlanogram(planogram, visionModelResponse as Parameters<typeof localMatchPlanogram>[1])
  }

  try {
    const response = await apiFetch(`${PLANOGRAM_PATH}/${planogramId}/match`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ visionModelResponse }),
    })
    return (await response.json()) as PlanogramMatchResult
  } catch {
    const list = localListPlanograms()
    const planogram = list.planograms.find((item) => item.id === planogramId)
    if (!planogram) {
      return null
    }
    return localMatchPlanogram(planogram, visionModelResponse as Parameters<typeof localMatchPlanogram>[1])
  }
}

export async function getActivePlanogramId(): Promise<string | null> {
  const list = await listPlanograms()
  return list.activePlanogramId
}
