/** Result returned by the shelf-image audit endpoint. */
export interface AuditAnalysisResult {
  /** Short recommended next step for store staff. */
  suggestedAction: string
  /** Longer reasoning that explains why the action was suggested. */
  explanation: string
}

export type AuditRequestStatus = 'idle' | 'ready' | 'uploading' | 'analyzing' | 'success' | 'error'

export interface AuditPanelState {
  status: AuditRequestStatus
  previewUrl: string | null
  fileName: string | null
  result: AuditAnalysisResult | null
  errorMessage: string | null
}
