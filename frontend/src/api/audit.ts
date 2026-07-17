/**
 * Upload a shelf image for gap / inventory analysis.
 *
 * Pipeline (progressive, with optional step callbacks):
 * 1) vision detect (model-local)
 * 2) planogram match
 * 3) agent analyze + ticket dispatch (backend)
 *
 * If the backend is unavailable, the frontend falls back to deterministic offline analysis.
 */
import type { AuditAnalysisResult } from '@/types'
import type { PlanogramMatchResult } from '@/types/planogram'

import type { Language } from '@/lib/i18n'

import { apiFetch, getApiBaseUrl } from './client'
import { getActivePlanogramId, matchPlanogramDetections } from './planogram'
import { captureCameraDetection, detectUploadedImage, type LocalDetectionResult } from './stream'

const DETECTION_AGENT_PATH = '/api/v1/audit/analyze-detections'

export type AuditPipelineStep =
  | 'vision'
  | 'planogram'
  | 'agent'
  | 'tickets'
  | 'done'

export interface AuditProgressEvent {
  step: AuditPipelineStep
  status: 'running' | 'done' | 'skipped' | 'error'
  message?: string
  partial?: Partial<AuditAnalysisResult>
}

export type AuditProgressHandler = (event: AuditProgressEvent) => void

export async function analyzeShelfImage(
  file: File,
  model: string,
  language: Language,
  onProgress?: AuditProgressHandler,
): Promise<AuditAnalysisResult> {
  onProgress?.({ step: 'vision', status: 'running' })
  const visionModelResponse = await detectUploadedImage(file, model)
  onProgress?.({
    step: 'vision',
    status: 'done',
    partial: {
      annotatedImage: visionModelResponse.annotatedImage,
      visionModelResponse,
      detections: visionModelResponse.detections,
      detectionSummary: visionModelResponse.summary,
    },
  })

  const imageBase64 = await fileToDataUrl(file)
  return analyzeVisionModelResponse(visionModelResponse, language, {
    imageBase64,
    sourceLabel: file.name,
    onProgress,
  })
}

export async function analyzeShelfCameraCapture(
  camera: string,
  model: string,
  language: Language,
  onProgress?: AuditProgressHandler,
): Promise<AuditAnalysisResult> {
  onProgress?.({ step: 'vision', status: 'running' })
  const visionModelResponse = await captureCameraDetection(camera, model)
  onProgress?.({
    step: 'vision',
    status: 'done',
    partial: {
      annotatedImage: visionModelResponse.annotatedImage,
      visionModelResponse,
      detections: visionModelResponse.detections,
      detectionSummary: visionModelResponse.summary,
    },
  })

  return analyzeVisionModelResponse(visionModelResponse, language, {
    imageBase64: visionModelResponse.annotatedImage ?? null,
    sourceLabel: `camera:${camera}`,
    onProgress,
  })
}

async function analyzeVisionModelResponse(
  visionModelResponse: LocalDetectionResult,
  language: Language,
  options: {
    imageBase64?: string | null
    sourceLabel?: string
    onProgress?: AuditProgressHandler
  } = {},
): Promise<AuditAnalysisResult> {
  const onProgress = options.onProgress

  onProgress?.({ step: 'planogram', status: 'running' })
  const planogramResponse = await queryPlanogramForDetections(visionModelResponse)
  onProgress?.({
    step: 'planogram',
    status: planogramResponse ? 'done' : 'skipped',
    partial: { planogramResponse },
  })

  onProgress?.({ step: 'agent', status: 'running' })
  const agentResponse = await requestAgentShelfRecommendation(
    visionModelResponse,
    planogramResponse,
    language,
    options,
  )
  onProgress?.({
    step: 'agent',
    status: 'done',
    partial: {
      suggestedAction: agentResponse.suggestedAction,
      explanation: agentResponse.explanation,
      recordId: agentResponse.recordId,
    },
  })

  onProgress?.({
    step: 'tickets',
    status: agentResponse.ticketIds && agentResponse.ticketIds.length > 0 ? 'done' : 'skipped',
    partial: {
      ticketIds: agentResponse.ticketIds,
      closedLoopNarrative: agentResponse.closedLoopNarrative,
    },
  })

  const result: AuditAnalysisResult = {
    ...agentResponse,
    annotatedImage: visionModelResponse.annotatedImage,
    visionModelResponse,
    detections: visionModelResponse.detections,
    detectionSummary: visionModelResponse.summary,
    planogramResponse,
  }

  onProgress?.({ step: 'done', status: 'done', partial: result })
  return result
}

async function queryPlanogramForDetections(
  visionModelResponse: LocalDetectionResult,
): Promise<PlanogramMatchResult | null> {
  const activeId = await getActivePlanogramId()
  if (!activeId) {
    return null
  }
  return matchPlanogramDetections(activeId, visionModelResponse)
}

async function requestAgentShelfRecommendation(
  visionModelResponse: LocalDetectionResult,
  planogramResponse: PlanogramMatchResult | null,
  language: Language,
  options: { imageBase64?: string | null; sourceLabel?: string } = {},
): Promise<
  Pick<AuditAnalysisResult, 'suggestedAction' | 'explanation' | 'recordId' | 'ticketIds' | 'closedLoopNarrative'>
> {
  if (getApiBaseUrl()) {
    try {
      const response = await apiFetch(DETECTION_AGENT_PATH, {
        method: 'POST',
        body: JSON.stringify({
          visionModelResponse,
          planogramResponse,
          language,
          imageBase64: options.imageBase64 ?? undefined,
          sourceLabel: options.sourceLabel ?? undefined,
        }),
        headers: {
          'Content-Type': 'application/json',
        },
      })
      return (await response.json()) as Pick<
        AuditAnalysisResult,
        'suggestedAction' | 'explanation' | 'recordId' | 'ticketIds' | 'closedLoopNarrative'
      >
    } catch {
      // Fall through to local deterministic analysis if the agent service is unavailable.
    }
  }

  const { gapCount, productCount, total } = visionModelResponse.summary
  const missing = planogramResponse?.missingItems ?? []
  const planogramName = planogramResponse?.planogramName

  if (language === 'zh') {
    let suggestedAction =
      gapCount > 0
        ? `复核 ${gapCount} 个货架空位并准备补货。`
        : total > 0
          ? '未检测到货架空位，继续常规监控。'
          : '未检测到商品或空位，请检查摄像头角度和图像质量。'
    if (missing.length === 1) {
      suggestedAction = `补货 ${missing[0].itemName || missing[0].sku}`
    } else if (missing.length > 1) {
      suggestedAction = `补货 ${missing.length} 个缺货 SKU`
    }

    let explanation =
      `本地视觉模型检测到 ${total} 个对象：${productCount} 个商品候选和 ${gapCount} 个空位候选。` +
      'Agent 后端不可用或未配置，因此当前使用基于视觉 JSON 的离线分析。'
    if (planogramResponse) {
      explanation += ` 已对照计划图「${planogramName}」。${planogramResponse.summary}`
    } else {
      explanation += ' 未选择计划图。'
    }
    return { suggestedAction, explanation }
  }

  let suggestedAction =
    gapCount > 0
      ? `Review ${gapCount} detected shelf gap${gapCount === 1 ? '' : 's'} and prepare replenishment.`
      : total > 0
        ? 'No shelf gaps detected. Continue routine monitoring.'
        : 'No products or gaps were detected. Verify camera angle and image quality.'
  if (missing.length === 1) {
    suggestedAction = `Restock ${missing[0].itemName || missing[0].sku}`
  } else if (missing.length > 1) {
    suggestedAction = `Restock ${missing.length} missing SKUs`
  }

  let explanation =
    `Local vision detected ${total} object${total === 1 ? '' : 's'}: ` +
    `${productCount} product candidate${productCount === 1 ? '' : 's'} and ` +
    `${gapCount} gap candidate${gapCount === 1 ? '' : 's'}. ` +
    'The backend is unavailable or not configured, so this offline recommendation only uses the vision-model JSON response.'
  if (planogramResponse) {
    explanation += ` Matched against planogram '${planogramName}'. ${planogramResponse.summary}`
  } else {
    explanation += ' No planogram was selected.'
  }

  return { suggestedAction, explanation }
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error ?? new Error('Failed to read image'))
    reader.readAsDataURL(file)
  })
}
