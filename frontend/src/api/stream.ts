const STREAM_BASE_URL =
  (import.meta.env.VITE_STREAM_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? 'http://localhost:8001'

const STREAM_PATH = '/api/v1/stream'
const DETECT_PATH = '/api/v1/detect'

export interface StreamCamera {
  id: string
  label: string
  /** Human-readable device name (e.g. "Integrated Camera") when resolvable. */
  name?: string
}

export interface StreamCamerasResponse {
  cameras: StreamCamera[]
  defaultCamera: string
}

export interface StreamModel {
  id: string
  label: string
  path: string
}

export interface StreamModelsResponse {
  models: StreamModel[]
  defaultModel: string
}

export interface DetectionBox {
  x1: number
  y1: number
  x2: number
  y2: number
  width: number
  height: number
}

export interface DetectionResultItem {
  label: string
  confidence: number
  classId: number | null
  box: DetectionBox
  normalizedBox: Omit<DetectionBox, 'width' | 'height'>
  /** True when this detection's box overlaps the motion mask (likely a person). */
  obscured?: boolean
}

/** Normalized bounding box of a motion/occlusion blob in [0, 1]. */
export interface OcclusionRegion {
  x1: number
  y1: number
  x2: number
  y2: number
}

/**
 * Temporal-occlusion metadata from a burst capture. When the view is obstructed
 * (a customer standing in front of the camera) the backend suppresses a false
 * camera_issue, and obscured facings are excluded from restock tickets.
 */
export interface OcclusionInfo {
  coverage: number
  viewObstructed: boolean
  regions: OcclusionRegion[]
  burstFrames: number
  /** Downscaled recent-audit frames folded into the long-baseline clean plate. */
  baselineFrames?: number
  /** True when the adaptive burst extended its window because the view stayed busy. */
  escalated?: boolean
}

export interface LocalDetectionResult {
  annotatedImage: string
  detections: DetectionResultItem[]
  summary: {
    total: number
    gapCount: number
    productCount: number
    obscuredCount?: number
  }
  occlusion?: OcclusionInfo
  image: {
    width: number
    height: number
  }
  model: string
  capturedAt: string
  camera?: string
}

export interface StreamStatusResponse {
  status: 'idle' | 'starting' | 'live' | 'error'
  error: string | null
  camera: string | null
  hasFrame: boolean
}

export interface StreamStatusesResponse {
  cameras: StreamStatusResponse[]
}

export function getStreamVideoUrl(camera?: string): string {
  const base = `${STREAM_BASE_URL}${STREAM_PATH}/video`
  if (camera == null || camera === '') {
    return base
  }
  return `${base}?camera=${encodeURIComponent(camera)}`
}

async function streamFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${STREAM_BASE_URL}${STREAM_PATH}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(detail || `Stream request failed with status ${response.status}`)
  }

  return (await response.json()) as T
}

async function detectFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${STREAM_BASE_URL}${DETECT_PATH}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(detail || `Detection request failed with status ${response.status}`)
  }

  return (await response.json()) as T
}

async function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(new Error('Could not read selected image.'))
    reader.readAsDataURL(file)
  })
}

export async function listStreamCameras(): Promise<StreamCamerasResponse> {
  return streamFetch<StreamCamerasResponse>('/cameras')
}

export async function listStreamModels(): Promise<StreamModelsResponse> {
  return streamFetch<StreamModelsResponse>('/models')
}

export async function getStreamStatus(camera?: string): Promise<StreamStatusResponse> {
  const query = camera == null || camera === '' ? '' : `?camera=${encodeURIComponent(camera)}`
  return streamFetch<StreamStatusResponse>(`/status${query}`)
}

/** Fetch the status of every camera the stream service is currently running. */
export async function getStreamStatuses(): Promise<StreamStatusesResponse> {
  return streamFetch<StreamStatusesResponse>('/statuses')
}

export async function startStream(camera: string, model?: string): Promise<StreamStatusResponse> {
  return streamFetch<StreamStatusResponse>('/start', {
    method: 'POST',
    body: JSON.stringify(model ? { camera, model } : { camera }),
  })
}

/** Stop a single camera when provided, or all cameras when omitted. */
export async function stopStream(camera?: string): Promise<unknown> {
  return streamFetch<unknown>('/stop', {
    method: 'POST',
    body: JSON.stringify(camera == null || camera === '' ? {} : { camera }),
  })
}

export async function detectUploadedImage(file: File, model: string): Promise<LocalDetectionResult> {
  const imageBase64 = await fileToDataUrl(file)
  return detectFetch<LocalDetectionResult>('/image', {
    method: 'POST',
    body: JSON.stringify({ imageBase64, model }),
  })
}

export async function captureCameraDetection(camera: string, model: string): Promise<LocalDetectionResult> {
  return detectFetch<LocalDetectionResult>('/capture', {
    method: 'POST',
    body: JSON.stringify({ camera, model }),
  })
}

/** Clean-plate still from a camera without running detection (planogram source photo). */
export interface CameraSnapshotResult {
  imageBase64: string
  image: { width: number; height: number }
  camera?: string
  burstFrames?: number
  baselineFrames?: number
  escalated?: boolean
  capturedAt?: string
}

export async function captureCameraSnapshot(camera: string): Promise<CameraSnapshotResult> {
  return detectFetch<CameraSnapshotResult>('/snapshot', {
    method: 'POST',
    // burstFrames defaults server-side; no model required for a plain still.
    body: JSON.stringify({ camera }),
  })
}
