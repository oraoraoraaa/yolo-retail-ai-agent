import type { AuditAnalysisResult } from '@/types'

import type { Language } from '@/lib/i18n'

import { apiFetch, getApiBaseUrl } from './client'
import { captureCameraDetection, detectUploadedImage, type LocalDetectionResult } from './stream'

const DETECTION_AGENT_PATH = '/api/v1/audit/analyze-detections'

/**
 * Upload a shelf image for gap / inventory analysis.
 *
 * The local model service returns annotated images + JSON detections. The
 * vision-model JSON is then sent to the agent backend for LLM analysis. If
 * the agent is unavailable, the frontend falls back to deterministic offline
 * analysis.
 */
export async function analyzeShelfImage(file: File, model: string, language: Language): Promise<AuditAnalysisResult> {
  const visionModelResponse = await detectUploadedImage(file, model)
  return analyzeVisionModelResponse(visionModelResponse, language)
}

export async function analyzeShelfCameraCapture(
  camera: string,
  model: string,
  language: Language,
): Promise<AuditAnalysisResult> {
  const visionModelResponse = await captureCameraDetection(camera, model)
  return analyzeVisionModelResponse(visionModelResponse, language)
}

async function analyzeVisionModelResponse(
  visionModelResponse: LocalDetectionResult,
  language: Language,
): Promise<AuditAnalysisResult> {
  const planogramResponse = await queryPlanogramForDetections(visionModelResponse)
  const agentResponse = await requestAgentShelfRecommendation(visionModelResponse, planogramResponse, language)

  return {
    ...agentResponse,
    annotatedImage: visionModelResponse.annotatedImage,
    visionModelResponse,
    detections: visionModelResponse.detections,
    detectionSummary: visionModelResponse.summary,
    planogramResponse,
  }
}

async function queryPlanogramForDetections(_visionModelResponse: LocalDetectionResult): Promise<null> {
  // TODO: connect this to the Planogram database described in doc/instruction.md.
  return null
}

async function requestAgentShelfRecommendation(
  visionModelResponse: LocalDetectionResult,
  planogramResponse: null,
  language: Language,
): Promise<Pick<AuditAnalysisResult, 'suggestedAction' | 'explanation'>> {
  if (getApiBaseUrl()) {
    try {
      const response = await apiFetch(DETECTION_AGENT_PATH, {
        method: 'POST',
        body: JSON.stringify({
          visionModelResponse,
          planogramResponse,
          language,
        }),
        headers: {
          'Content-Type': 'application/json',
        },
      })
      return (await response.json()) as Pick<AuditAnalysisResult, 'suggestedAction' | 'explanation'>
    } catch {
      // Fall through to local deterministic analysis if the agent service is unavailable.
    }
  }

  const { gapCount, productCount, total } = visionModelResponse.summary
  if (language === 'zh') {
    return {
      suggestedAction:
        gapCount > 0
          ? `复核 ${gapCount} 个货架空位并准备补货。`
          : total > 0
            ? '未检测到货架空位，继续常规监控。'
            : '未检测到商品或空位，请检查摄像头角度和图像质量。',
      explanation:
        `本地视觉模型检测到 ${total} 个对象：${productCount} 个商品候选和 ${gapCount} 个空位候选。` +
        'Agent 后端不可用或未配置，因此当前使用基于视觉 JSON 的离线分析。',
    }
  }

  const suggestedAction =
    gapCount > 0
      ? `Review ${gapCount} detected shelf gap${gapCount === 1 ? '' : 's'} and prepare replenishment.`
      : total > 0
        ? 'No shelf gaps detected. Continue routine monitoring.'
        : 'No products or gaps were detected. Verify camera angle and image quality.'

  return {
    suggestedAction,
    explanation:
      `Local vision detected ${total} object${total === 1 ? '' : 's'}: ` +
      `${productCount} product candidate${productCount === 1 ? '' : 's'} and ` +
      `${gapCount} gap candidate${gapCount === 1 ? '' : 's'}. ` +
      'The agent backend is unavailable or not configured, so this offline recommendation only uses the vision-model JSON response.',
  }
}
