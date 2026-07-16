const STREAM_BASE_URL =
  (import.meta.env.VITE_STREAM_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? 'http://localhost:8001'

const STREAM_PATH = '/api/v1/stream'
const DETECT_PATH = '/api/v1/detect'

export interface StreamCamera {
  id: string
  label: string
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
}

export interface LocalDetectionResult {
  annotatedImage: string
  detections: DetectionResultItem[]
  summary: {
    total: number
    gapCount: number
    productCount: number
  }
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

export function getStreamVideoUrl(): string {
  return `${STREAM_BASE_URL}${STREAM_PATH}/video`
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

export async function getStreamStatus(): Promise<StreamStatusResponse> {
  return streamFetch<StreamStatusResponse>('/status')
}

export async function startStream(camera: string): Promise<StreamStatusResponse> {
  return streamFetch<StreamStatusResponse>('/start', {
    method: 'POST',
    body: JSON.stringify({ camera }),
  })
}

export async function stopStream(): Promise<StreamStatusResponse> {
  return streamFetch<StreamStatusResponse>('/stop', {
    method: 'POST',
    body: JSON.stringify({}),
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
