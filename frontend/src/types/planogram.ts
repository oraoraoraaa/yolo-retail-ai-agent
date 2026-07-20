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

/** Full planogram record (SQL-backed agent store). */
export interface Planogram {
  id: string
  name: string
  description: string
  imageBase64: string
  imageWidth: number
  imageHeight: number
  imageRef?: string | null
  imageUrl?: string | null
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
  matches: PlanogramSlotMatch[]
  gapMatches: PlanogramSlotMatch[]
  /**
   * Facings currently occluded (e.g. a customer standing in front). These are
   * deliberately excluded from missingItems so they never open false tickets.
   */
  obscuredMatches: PlanogramSlotMatch[]
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
  /**
   * Planogram slots whose recorded stock is 0 (or below), regardless of whether
   * a gap was detected. Out-of-stock is planogram ground truth, so the backroom
   * replenishment ticket fires from this list even when the camera sees no gap.
   */
  outOfStockSlots: Array<{
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
  }>
  summary: string
}

export interface PlanogramSlotMatch {
  detectionLabel: string
  confidence?: number
  slotId?: string | null
  center?: { x: number; y: number }
  slot: PlanogramSlot | null
  status: 'gap' | 'product' | 'obscured' | string
  obscured?: boolean
}

export type PlanogramEditorMode = 'list' | 'create' | 'edit'
