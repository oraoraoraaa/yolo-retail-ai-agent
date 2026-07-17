import type { DetectionResultItem, LocalDetectionResult } from '@/api/stream'
import type { PlanogramMatchResult } from '@/types/planogram'

/** Result returned by the shelf-image audit endpoint. */
export interface AuditAnalysisResult {
  /** Short recommended next step for store staff. */
  suggestedAction: string
  /** Longer reasoning that explains why the action was suggested. */
  explanation: string
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

export interface AuditPanelState {
  status: AuditRequestStatus
  previewUrl: string | null
  fileName: string | null
  result: AuditAnalysisResult | null
  errorMessage: string | null
}
