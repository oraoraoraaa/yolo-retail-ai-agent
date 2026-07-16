const STREAM_BASE_URL =
  (import.meta.env.VITE_STREAM_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? 'http://localhost:8001'

const STREAM_PATH = '/api/v1/stream'

export interface StreamCamera {
  id: string
  label: string
}

export interface StreamCamerasResponse {
  cameras: StreamCamera[]
  defaultCamera: string
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

export async function listStreamCameras(): Promise<StreamCamerasResponse> {
  return streamFetch<StreamCamerasResponse>('/cameras')
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
