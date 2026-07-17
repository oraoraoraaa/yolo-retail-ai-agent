import type { DetectionResultItem, LocalDetectionResult } from '@/api/stream'
import type { PlanogramMatchResult } from '@/types/planogram'

/** Result returned by the shelf-image audit endpoint. */
export interface AuditAnalysisResult {
  /** Short recommended next step for store staff. */
  suggestedAction: string
  /** Longer reasoning that explains why the action was suggested. */
  explanation: string
  /** Persisted audit record id when the backend saved the run. */
  recordId?: string
  /** Closed-loop ticket ids created or updated by this audit. */
  ticketIds?: string[]
  /** Optional Detect → Decide → Dispatch narrative from the closed-loop agent. */
  closedLoopNarrative?: string | null
  /** JPEG data URL with model bounding boxes drawn on the shelf image. */
  annotatedImage?: string
  /** Structured local vision-model response sent to the agent layer. */
  visionModelResponse?: LocalDetectionResult
  detections?: DetectionResultItem[]
  detectionSummary?: LocalDetectionResult['summary']
  /** Active planogram match result (null when no planogram is selected). */
  planogramResponse?: PlanogramMatchResult | null
}

export type AuditRequestStatus = 'idle' | 'ready' | 'uploading' | 'analyzing' | 'success' | 'error'

export type AuditPipelineStep = 'vision' | 'planogram' | 'agent' | 'tickets' | 'done'

export type AuditStepStatus = 'pending' | 'running' | 'done' | 'skipped' | 'error'

export interface AuditStepState {
  id: AuditPipelineStep
  status: AuditStepStatus
}

export interface AuditPanelState {
  status: AuditRequestStatus
  previewUrl: string | null
  fileName: string | null
  result: AuditAnalysisResult | null
  errorMessage: string | null
  /** Progressive pipeline steps shown while analyzing. */
  steps: AuditStepState[]
  /** Currently active step id while analyzing. */
  activeStep: AuditPipelineStep | null
}

export const AUDIT_PIPELINE_STEPS: AuditPipelineStep[] = [
  'vision',
  'planogram',
  'agent',
  'tickets',
  'done',
]

export function createInitialAuditSteps(): AuditStepState[] {
  return AUDIT_PIPELINE_STEPS.map((id) => ({ id, status: 'pending' }))
}
