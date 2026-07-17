/** One facing region drawn on a shelf planogram (normalized box in [0, 1]). */
export interface PlanogramSlot {
  id: string
  x: number
  y: number
  width: number
  height: number
  itemName: string
  itemPrice: number | null
  itemStock: number
  sku: string
  notes: string
}

/** Full planogram record (agent in-memory store). */
export interface Planogram {
  id: string
  name: string
  description: string
  imageBase64: string
  imageWidth: number
  imageHeight: number
  slots: PlanogramSlot[]
  createdAt: string
  updatedAt: string
}

export interface PlanogramCreatePayload {
  name: string
  description?: string
  imageBase64?: string
  imageWidth?: number
  imageHeight?: number
  slots: PlanogramSlot[]
}

export interface PlanogramUpdatePayload {
  name?: string
  description?: string
  imageBase64?: string
  imageWidth?: number
  imageHeight?: number
  slots?: PlanogramSlot[]
}

export interface PlanogramListResult {
  planograms: Planogram[]
  activePlanogramId: string | null
}

export interface PlanogramMatchResult {
  planogramId: string
  planogramName: string
  slotCount: number
  matches: Array<{
    detectionLabel: string
    confidence?: number
    slotId?: string | null
    center?: { x: number; y: number }
    slot: PlanogramSlot | null
    status: 'gap' | 'product' | string
  }>
  gapMatches: Array<{
    detectionLabel: string
    confidence?: number
    slotId?: string | null
    center?: { x: number; y: number }
    slot: PlanogramSlot | null
    status: 'gap' | 'product' | string
  }>
  missingItems: Array<{
    slotId: string
    x: number
    y: number
    width: number
    height: number
    itemName: string
    itemPrice: number | null
    itemStock: number
    sku: string
    notes: string
    confidence?: number
  }>
  summary: string
}

export type PlanogramEditorMode = 'list' | 'create' | 'edit'
