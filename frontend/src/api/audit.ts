import type { AuditAnalysisResult } from '@/types'

import { apiFetch, getApiBaseUrl } from './client'

const AUDIT_PATH = '/api/v1/audit/analyze'

/**
 * Upload a shelf image for gap / inventory analysis.
 *
 * Backend contract (planned):
 * - Method: POST multipart/form-data
 * - Field: `image` (File)
 * - Response JSON: { suggestedAction: string, explanation: string }
 *
 * Until the backend exists this returns empty strings.
 */
export async function analyzeShelfImage(file: File): Promise<AuditAnalysisResult> {
  if (!getApiBaseUrl()) {
    return {
      suggestedAction: 'Backend is not configured.',
      explanation: 'Set VITE_API_BASE_URL to enable shelf-image analysis.',
    }
  }

  const body = new FormData()
  body.append('image', file)

  const response = await apiFetch(AUDIT_PATH, {
    method: 'POST',
    body,
  })

  return (await response.json()) as AuditAnalysisResult
}
